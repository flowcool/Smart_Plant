"""Offline executor for the display scripts, read directly from package YAML.

Only the action primitives used by these scripts are supported. C++ lambdas
run unchanged in a native library with fake globals, time and GPIO. Script
restart/stop cancels the caller's continuation and waits, not called scripts,
matching ESPHome 2026.9.0 script.h / automation.h / base_automation.h.
This checks automation flow up to deep_sleep.enter. The driver shutdown hook
can still send SPI; physical sleep timing is outside this executor.
"""

import ctypes
from pathlib import Path
import re
import subprocess
import tempfile

import yaml


class PackageLoader(yaml.SafeLoader):
    pass


PackageLoader.add_multi_constructor(
    "!", lambda loader, tag, node: loader.construct_scalar(node)
)


class DisplayProgram:
    def __init__(self, root, profile=None, standalone=False):
        if standalone:
            core = yaml.load((Path(root) / "docs/source/files/configuration.yaml").read_text(), PackageLoader)
            transport = {"script": []}
        else:
            packages = Path(root) / "examples/multi-device/packages"
            core = yaml.load((packages / "smart_plant_core.yaml").read_text(), PackageLoader)
            transport = yaml.load(
                (packages / f"smart_plant_profile_{profile}.yaml").read_text(), PackageLoader
            )
        self.substitutions = core["substitutions"]
        available = {s["id"]: s for p in (core, transport) for s in p["script"]}
        # Extract the actual refresh boundary at every caller, including the
        # maintenance path. Surrounding plant/page decisions are irrelevant to
        # cancellation; keep the real prepare/update/settle/wait action order.
        self.refresh_sequences = []

        def refreshes(node):
            if isinstance(node, list):
                for index, child in enumerate(node):
                    if child == {"component.update": "my_display"}:
                        start = index - 1 if index and "script.execute" in node[index - 1] else index
                        self.refresh_sequences.append(node[start:index + 3])
                    refreshes(child)
            elif isinstance(node, dict):
                for value in node.values():
                    refreshes(value)

        for package in (core, transport):
            refreshes(package.get("script", []))
        self.scripts = {}
        pending = ["settle_display", "enter_deep_sleep", "sleep_after_display"]
        if standalone:
            pending.append("consider_deep_sleep")
        for sequence in self.refresh_sequences:
            for action in sequence:
                if "script.execute" in action:
                    pending.append(action["script.execute"])
        snippets = set()

        def visit(node):
            if isinstance(node, list):
                for child in node:
                    visit(child)
            elif isinstance(node, dict):
                for key, value in node.items():
                    if key in ("logger.log", "mqtt.publish"):
                        continue  # Outputs are recorded, not sent or formatted.
                    if key == "lambda":
                        snippets.add(value)
                    elif key in ("script.execute", "script.stop", "script.wait", "script.is_running"):
                        pending.append(value)
                    else:
                        visit(value)

        while pending:
            name = pending.pop()
            if name not in self.scripts:
                self.scripts[name] = available[name]
                visit(available[name]["then"])

        fields = [(g["id"], g["type"], g["initial_value"]) for g in core["globals"]]
        fields += [("busy", "int", "0"), ("reset_low_count", "int", "0"),
                   ("reset_high_count", "int", "0"), ("now", "uint32_t", "0")]
        if standalone:
            fields.append(("esptime", "Clock", "0"))

        class Clock(ctypes.Structure):
            _fields_ = [("valid", ctypes.c_bool)]
        types = {"bool": ctypes.c_bool, "int": ctypes.c_int, "uint32_t": ctypes.c_uint32, "Clock": Clock}

        class State(ctypes.Structure):
            _fields_ = [(name, types[kind]) for name, kind, _ in fields]

        self.State = State
        self.initial = {name: Clock(False) if kind == "Clock" else value == "true" if kind == "bool" else int(value)
                        for name, kind, value in fields}
        source = ["#include <cstdint>\n#include <type_traits>\n",
                  "struct Now { bool valid; bool is_valid() { return valid; } };"
                  "struct Clock { bool valid; Now now() { return {valid}; } };",
                  "struct State {" + "".join(f"{kind} {name};" for name, kind, _ in fields) + "};",
                  "constexpr int HIGH=1, LOW=0, OUTPUT=1;",
                  "#define id(name) state->name",
                  "template<class F> double invoke(F f) { if constexpr "
                  "(std::is_void_v<decltype(f())>) { f(); return 0; } else return f(); }"]
        self.functions = {}
        for index, snippet in enumerate(sorted(snippets)):
            body = self.expand(snippet)
            source.append(
                f'extern "C" double run_{index}(State *state) {{'
                "auto digitalRead = [&](int) { return state->busy; };"
                "auto pinMode = [](int, int) {};"
                "auto digitalWrite = [&](int, int level) {"
                "if (level == LOW) state->reset_low_count++; else state->reset_high_count++; };"
                "auto millis = [&]() { return state->now; };"
                f"return invoke([&]() {{ {body} }}); }}"
            )
            self.functions[snippet] = f"run_{index}"
        self.temp = tempfile.TemporaryDirectory(prefix="smart-plant-display-")
        native = Path(self.temp.name)
        (native / "lambdas.cpp").write_text("\n".join(source))
        subprocess.run(["c++", "-std=c++20", "-shared", "-fPIC", "-O0",
                        str(native / "lambdas.cpp"), "-o", str(native / "lambdas.so")], check=True)
        self.library = ctypes.CDLL(str(native / "lambdas.so"))
        for snippet, name in self.functions.items():
            function = getattr(self.library, name)
            function.argtypes = [ctypes.POINTER(State)]
            function.restype = ctypes.c_double
            self.functions[snippet] = function

    def close(self):
        self.temp.cleanup()

    def expand(self, value):
        return re.sub(r"\$\{([^}]+)\}", lambda m: self.expand(self.substitutions[m[1]]), value)

    def duration(self, value):
        value = self.expand(str(value))
        match = re.fullmatch(r"([\d.]+)(ms|s|min|h)", value)
        if not match:
            raise ValueError(f"Unsupported duration: {value}")
        return round(float(match[1]) * {"ms": 1, "s": 1000, "min": 60000, "h": 3600000}[match[2]])


class DisplayRuntime:
    TICK = 10

    def __init__(self, program, busy=lambda ms: 0, reverse_schedule=False):
        self.program = program
        self.state = program.State(**program.initial)
        self.busy = busy
        self.reverse_schedule = reverse_schedule
        self.tasks = {}
        self.events = []
        self.sleep = None

    def refresh(self, index=0):
        name = "__refresh_caller"
        task = {"alive": True, "name": name}
        task["actions"] = self.actions(self.program.refresh_sequences[index], task)
        self.tasks[name] = task
        self.resume(task)

    def condition(self, condition):
        if len(condition) != 1:
            raise ValueError(f"Unsupported condition: {condition}")
        key, value = next(iter(condition.items()))
        if key == "lambda":
            return bool(self.program.functions[value](ctypes.byref(self.state)))
        if key == "script.is_running":
            return value in self.tasks
        if key == "not":
            return not self.condition(value)
        raise ValueError(f"Unsupported condition: {key}")

    def stop(self, name):
        task = self.tasks.pop(name, None)
        if task:
            task["alive"] = False

    def execute(self, name):
        script = self.program.scripts[name]
        if name in self.tasks:
            if script.get("mode", "single") == "single":
                return
            if script["mode"] != "restart":
                raise ValueError("Only single/restart scripts are supported")
            self.stop(name)
        self.events.append((self.state.now, "script.execute", name))
        task = {"alive": True, "name": name}
        task["actions"] = self.actions(script["then"], task)
        self.tasks[name] = task
        self.resume(task)

    def actions(self, actions, task):
        for action in actions:
            if not task["alive"] or self.sleep:
                return
            if isinstance(action, str):
                key, value = action, None
            elif len(action) == 1:
                key, value = next(iter(action.items()))
            else:
                raise ValueError(f"Unsupported action: {action}")
            if key == "lambda":
                self.program.functions[value](ctypes.byref(self.state))
            elif key == "if":
                branch = "then" if self.condition(value["condition"]) else "else"
                yield from self.actions(value.get(branch, []), task)
            elif key == "script.execute":
                self.execute(value)
            elif key == "script.stop":
                self.stop(value)
            elif key == "script.wait":
                if value in self.tasks:
                    yield ("script.wait", value, None)
            elif key == "delay":
                yield ("delay", None, self.state.now + self.program.duration(value))
            elif key == "wait_until":
                if not self.condition(value["condition"]):
                    yield ("wait_until", value["condition"],
                           self.state.now + self.program.duration(value["timeout"]))
            elif key == "component.update":
                if value != "my_display":
                    raise ValueError(f"Unsupported component: {value}")
                if self.state.reset_low_count != self.state.reset_high_count:
                    raise AssertionError("Display SPI update occurred while RST was LOW")
                self.events.append((self.state.now, key, value))
            elif key == "deep_sleep.enter":
                duration = value.get("sleep_duration", "1h") if isinstance(value, dict) else "1h"
                self.sleep = (self.state.now, self.program.duration(duration))
                self.events.append((self.state.now, key, duration))
            elif key in ("deep_sleep.allow", "deep_sleep.prevent", "switch.turn_off",
                         "logger.log", "mqtt.publish", "text_sensor.template.publish",
                         "safe_mode.mark_successful"):
                self.events.append((self.state.now, key, value))
            else:
                raise ValueError(f"Unsupported action: {key}")

    def resume(self, task):
        try:
            task["wait"] = next(task["actions"])
        except StopIteration:
            if task["alive"]:
                self.tasks.pop(task["name"], None)
                task["alive"] = False

    def run_until(self, ms):
        while self.state.now < ms and not self.sleep:
            self.state.now += self.TICK
            self.state.busy = self.busy(self.state.now)
            for task in list(self.tasks.values())[:: -1 if self.reverse_schedule else 1]:
                if not task["alive"]:
                    continue
                kind, value, deadline = task["wait"]
                ready = deadline is not None and self.state.now >= deadline
                if kind == "wait_until":
                    ready = ready or self.condition(value)
                elif kind == "script.wait":
                    ready = value not in self.tasks
                if ready:
                    self.resume(task)
