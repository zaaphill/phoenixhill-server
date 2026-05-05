import json
import threading

from direct.gui.DirectGui import DirectFrame, DirectLabel, DirectEntry, DirectButton

import auth_client

DARK    = (0.11, 0.12, 0.17, 0.97)
MED     = (0.17, 0.19, 0.26, 1.0)
BTN     = (0.19, 0.21, 0.29, 1.0)
SEL     = (0.18, 0.38, 0.72, 1.0)
TEXT    = (0.88, 0.90, 0.95, 1.0)
TEXT_D  = (0.54, 0.57, 0.65, 1.0)
GREEN   = (0.40, 0.88, 0.52, 1.0)
RED     = (1.00, 0.40, 0.40, 1.0)


class CloudMixin:

    # ── Public entry point (called from Save button) ───────────────────────

    def cloud_save_build(self):
        token = getattr(self, "_session_token", None)
        if not token:
            return
        if getattr(self, "_cloud_build_id", None):
            self._do_cloud_update()
        else:
            self._show_save_dialog()

    # ── Save-name dialog ───────────────────────────────────────────────────

    def _show_save_dialog(self):
        if getattr(self, "_save_dialog", None):
            return
        self._save_dialog = DirectFrame(
            frameColor=DARK,
            frameSize=(-0.42, 0.42, -0.22, 0.22),
            sortOrder=200,
        )
        DirectLabel(
            text="Save Build",
            text_fg=TEXT, text_scale=0.050,
            frameColor=(0, 0, 0, 0),
            parent=self._save_dialog, pos=(0, 0, 0.135),
        )
        DirectLabel(
            text="Name:",
            text_fg=TEXT_D, text_scale=0.036,
            frameColor=(0, 0, 0, 0),
            parent=self._save_dialog, pos=(-0.20, 0, 0.048),
        )
        self._save_name_entry = DirectEntry(
            text_fg=TEXT, text_scale=0.038,
            frameColor=MED,
            width=15, numLines=1,
            parent=self._save_dialog,
            pos=(-0.35, 0, -0.025),
            initialText=getattr(self, "_cloud_build_name", "") or "",
            focus=1,
            command=self._on_save_dialog_enter,
        )
        DirectButton(
            text="Save",
            text_fg=TEXT, text_scale=0.038,
            frameColor=SEL,
            frameSize=(-0.105, 0.105, -0.032, 0.032),
            parent=self._save_dialog, pos=(-0.155, 0, -0.148),
            command=self._on_save_dialog_confirm, relief=1,
        )
        DirectButton(
            text="Cancel",
            text_fg=TEXT_D, text_scale=0.038,
            frameColor=BTN,
            frameSize=(-0.105, 0.105, -0.032, 0.032),
            parent=self._save_dialog, pos=(0.155, 0, -0.148),
            command=self._dismiss_save_dialog, relief=1,
        )

    def _on_save_dialog_enter(self, _text):
        self._on_save_dialog_confirm()

    def _on_save_dialog_confirm(self):
        name = self._save_name_entry.get().strip()
        if not name:
            return
        self._dismiss_save_dialog()
        self._cloud_build_name = name
        self._do_cloud_create(name)

    def _dismiss_save_dialog(self):
        dlg = getattr(self, "_save_dialog", None)
        if dlg:
            dlg.destroy()
            self._save_dialog = None

    # ── Actual network calls ───────────────────────────────────────────────

    def _do_cloud_create(self, name):
        token    = self._session_token
        data_str = json.dumps(self.get_build_data())
        def worker():
            result, err = auth_client.create_build(token, name, data_str)
            if result and result.get("ok"):
                self._cloud_build_id = result["id"]
                self.taskMgr.doMethodLater(
                    0, self._on_save_ok, "_saveOk", appendTask=True)
            else:
                self.taskMgr.doMethodLater(
                    0, self._on_save_fail, "_saveFail",
                    extraArgs=[err or "Save failed."], appendTask=True)
        threading.Thread(target=worker, daemon=True).start()

    def _do_cloud_update(self):
        token    = self._session_token
        build_id = self._cloud_build_id
        name     = self._cloud_build_name
        data_str = json.dumps(self.get_build_data())
        def worker():
            result, err = auth_client.update_build(token, build_id, name, data_str)
            if result and result.get("ok"):
                self.taskMgr.doMethodLater(
                    0, self._on_save_ok, "_saveOk", appendTask=True)
            else:
                self.taskMgr.doMethodLater(
                    0, self._on_save_fail, "_saveFail",
                    extraArgs=[err or "Save failed."], appendTask=True)
        threading.Thread(target=worker, daemon=True).start()

    def _on_save_ok(self, task):
        self._show_toast(f"Saved \"{self._cloud_build_name}\"", GREEN)
        return task.done

    def _on_save_fail(self, msg, task):
        self._show_toast(msg, RED)
        return task.done

    # ── Load a build into the scene (called from main menu) ───────────────

    def cloud_load_into_scene(self, build_id, name, data_str):
        """Parse data and replace scene contents. Must be called on main thread."""
        self._cloud_build_id   = build_id
        self._cloud_build_name = name
        try:
            self._load_bricks_from_data(json.loads(data_str))
        except Exception as e:
            print("Cloud load error:", e)

    # ── Toast notification ─────────────────────────────────────────────────

    def _show_toast(self, msg, color=None):
        if color is None:
            color = GREEN
        prev = getattr(self, "_toast", None)
        if prev:
            try:
                prev.destroy()
            except Exception:
                pass
        self._toast = DirectLabel(
            text=msg,
            text_fg=color, text_scale=0.036,
            frameColor=(0.07, 0.08, 0.11, 0.92),
            frameSize=(-0.34, 0.34, -0.026, 0.026),
            pos=(0, 0, -0.88),
        )
        self.taskMgr.doMethodLater(2.5, self._dismiss_toast, "_dismissToast",
                                   appendTask=True)

    def _dismiss_toast(self, task):
        t = getattr(self, "_toast", None)
        if t:
            try:
                t.destroy()
            except Exception:
                pass
            self._toast = None
        return task.done
