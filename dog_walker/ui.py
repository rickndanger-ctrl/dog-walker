"""Terminal dashboard and explicit review controls."""
import asyncio
import json
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, RichLog, Static, Switch, TextArea
from .engine import Engine


class EditPrompt(ModalScreen[str | None]):
    CSS = """EditPrompt { align: center middle; } #editor { width: 90%; height: 80%; background: $surface; border: thick $accent; padding: 1; } TextArea { height: 1fr; }"""

    def __init__(self, text):
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        with Vertical(id="editor"):
            yield Static("Edit the prompt for this retry")
            yield TextArea(self.text, id="prompt")
            with Horizontal():
                yield Button("Send edited prompt", id="send", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(self.query_one("#prompt", TextArea).text if event.button.id == "send" else None)


class Dashboard(App):
    TITLE = "Dog Walker • Offline"
    CSS = """
    Screen { background: #101827; }
    #status { height: auto; padding: 1 2; background: #1b2940; }
    #log { height: 1fr; padding: 0 1; border: round #4e7299; }
    #gate { height: auto; min-height: 3; padding: 1 2; color: #ffd88a; }
    #controls { height: 3; padding: 0 1; }
    Button { margin-right: 1; min-width: 9; }
    #mode { height: 3; padding-left: 2; }
    #mode Static { width: auto; padding: 1 1 0 0; }
    """
    BINDINGS = [("ctrl+c", "pause_run", "Pause"), ("q", "leave", "Exit"), ("a", "approve", "Approve"), ("r", "retry", "Retry")]

    def __init__(self, store, no_start=False):
        super().__init__()
        self.store, self.no_start = store, no_start
        self.waiting = None
        self.walk_task = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="status")
        yield RichLog(id="log", wrap=True, markup=False, highlight=False, max_lines=3000)
        yield Static("Starting…", id="gate")
        with Horizontal(id="mode"):
            yield Static("Automatic advancement")
            yield Switch(value=self.store.state["auto"], id="auto")
            yield Static("Uncertain checkpoints still pause for review")
        with Horizontal(id="controls"):
            for label, ident, variant in [("Approve", "approve", "success"), ("Retry", "retry", "primary"), ("Edit", "edit", "default"), ("Skip", "skip", "warning"), ("Pause", "pause", "default"), ("Abort", "abort", "error")]:
                yield Button(label, id=ident, variant=variant)
        yield Footer()

    def on_mount(self):
        self.set_interval(1, self.refresh_status)
        self.walk_task = asyncio.create_task(self.walk())

    def refresh_status(self):
        s = self.store.state
        self.query_one("#status", Static).update(f"{s['name']}  |  {s['status']}  |  Step: {s['step']}  |  Turn: {s['turns']}\nRun: {s['id']}\nWorkspace: {s['root']}")
        for ident in ("approve", "retry", "edit", "skip"):
            self.query_one(f"#{ident}", Button).disabled = self.waiting is None

    def emit(self, text):
        self.query_one("#log", RichLog).write(text)

    async def ask(self, reason, passed):
        self.query_one("#gate", Static).update(reason)
        self.waiting = asyncio.get_running_loop().create_future()
        self.refresh_status()
        try:
            return await self.waiting
        finally:
            self.waiting = None
            self.query_one("#gate", Static).update("Working locally…")

    async def walk(self):
        try:
            await Engine(self.store, self.emit, self.ask, self.no_start).run()
        except asyncio.CancelledError:
            pass
        self.refresh_status()
        self.query_one("#gate", Static).update(f"Run {self.store.state['status']}. Press q to exit. Files and logs are retained.")

    def answer(self, value):
        if self.waiting and not self.waiting.done():
            self.waiting.set_result(value)

    def on_switch_changed(self, event: Switch.Changed):
        self.store.save(auto=event.value)

    async def on_button_pressed(self, event: Button.Pressed):
        ident = event.button.id
        if ident == "edit" and self.waiting:
            s = self.store.state
            text = self.store.workflow().prompt(s["step"], project_root=s["root"], step_id=s["step"],
                previous_result=json.dumps(s.get("result") or {}),
                failed_checks="\n".join((s.get("evaluation") or {}).get("failed", [])))

            def edited(value):
                if value and value.strip():
                    self.answer("edit:" + value)

            self.push_screen(EditPrompt(text), edited)
        elif ident == "pause":
            await self.action_pause_run()
        elif ident == "abort" and not self.waiting:
            await self.action_pause_run()
            self.store.save(status="aborted")
            self.store.event("aborted")
            self.refresh_status()
        else:
            self.answer(ident)

    def action_approve(self):
        self.answer("approve")

    def action_retry(self):
        self.answer("retry")

    async def action_pause_run(self):
        if self.waiting:
            self.answer("pause")
        elif self.walk_task and not self.walk_task.done():
            self.walk_task.cancel()
        if self.walk_task:
            await self.walk_task

    async def action_leave(self):
        await self.action_pause_run()
        self.exit()
