import json
import threading

from direct.gui.DirectGui import DirectFrame, DirectLabel, DirectEntry, DirectButton
from panda3d.core import TextNode

import auth_client

DARK    = (0.11, 0.13, 0.18, 0.98)
HEADER  = (0.08, 0.09, 0.13, 1.00)
FIELD   = (0.08, 0.09, 0.13, 1.00)
BTN     = (0.17, 0.19, 0.26, 1.00)
SEL     = (0.18, 0.38, 0.72, 1.00)
TEXT    = (0.90, 0.93, 0.98, 1.00)
TEXT_D  = (0.50, 0.54, 0.64, 1.00)
GREEN   = (0.40, 0.88, 0.52, 1.00)
RED     = (1.00, 0.40, 0.40, 1.00)


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
        # Block movement keys while the dialog is open
        self._ui_modal_open = True
        for k in getattr(self, 'keys', {}):
            self.keys[k] = False

        W, H   = 0.40, 0.22   # half-width / half-height of dialog
        TS     = 0.034         # entry text scale
        PAD    = 0.04          # horizontal padding inside dialog
        IW     = W - PAD       # inner half-width (usable content area)

        self._save_dialog = DirectFrame(
            frameColor=DARK,
            frameSize=(-W, W, -H, H),
            sortOrder=200,
        )

        # Header strip
        DirectFrame(
            frameColor=HEADER,
            frameSize=(-W, W, -0.046, 0.046),
            parent=self._save_dialog,
            pos=(0, 0, H - 0.046),
        )
        DirectLabel(
            text="Save Build",
            text_fg=TEXT, text_scale=0.040,
            frameColor=(0, 0, 0, 0),
            parent=self._save_dialog,
            pos=(0, 0, H - 0.076),
        )

        # "Build name" hint label
        DirectLabel(
            text="BUILD NAME",
            text_fg=TEXT_D, text_scale=0.024,
            frameColor=(0, 0, 0, 0),
            text_align=TextNode.ALeft,
            parent=self._save_dialog,
            pos=(-IW, 0, 0.055),
        )

        # Explicit background for entry (avoids DirectEntry frame overflow)
        DirectFrame(
            frameColor=FIELD,
            frameSize=(-IW, IW, -0.036, 0.036),
            parent=self._save_dialog,
            pos=(0, 0, 0.006),
        )
        self._save_name_entry = DirectEntry(
            text_fg=TEXT, text_scale=TS,
            frameColor=(0, 0, 0, 0),
            relief=None,
            width=int(IW * 2 / TS),
            numLines=1,
            parent=self._save_dialog,
            pos=(-IW + 0.010, 0, -0.010),
            initialText=getattr(self, "_cloud_build_name", "") or "",
            focus=1,
            command=self._on_save_dialog_enter,
        )

        # Buttons
        bkw = dict(relief=1, text_scale=0.034,
                   frameSize=(-0.110, 0.110, -0.034, 0.034))
        DirectButton(
            text="Save", text_fg=TEXT, frameColor=SEL,
            parent=self._save_dialog, pos=(-0.14, 0, -(H - 0.050)),
            command=self._on_save_dialog_confirm, **bkw,
        )
        DirectButton(
            text="Cancel", text_fg=TEXT_D, frameColor=BTN,
            parent=self._save_dialog, pos=(0.14, 0, -(H - 0.050)),
            command=self._dismiss_save_dialog, **bkw,
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
        self._ui_modal_open = False
        for k in getattr(self, 'keys', {}):
            self.keys[k] = False

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

    def _show_toast(self, msg, color=None, duration=2.5):
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
        self.taskMgr.doMethodLater(duration, self._dismiss_toast, "_dismissToast",
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
