import datetime
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time

# Request native-resolution rendering before Windows creates any UI handles.
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()

import numpy as np
import soundfile as sf
import wx
import wx.media
import wx.adv
from wx.lib.buttons import GenButton


APP_DIR = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else pathlib.Path(__file__).resolve().parent
BUNDLED_RUNTIME = APP_DIR / "runtime"
MSST_ROOT = pathlib.Path(os.environ.get("MSST_ROOT", str(BUNDLED_RUNTIME) if BUNDLED_RUNTIME.is_dir() else str(APP_DIR / "runtime")))
PYTHON_EXE = MSST_ROOT / "env" / "python.exe"
INFERENCE_SCRIPT = MSST_ROOT / "inference.py"
MODEL_INDEX = MSST_ROOT / "model_config_zh.json"
DATA_ROOT = pathlib.Path(os.environ.get("LOCALAPPDATA", str(pathlib.Path.home()))) / "MSST-Studio" if BUNDLED_RUNTIME.is_dir() else MSST_ROOT / "MSST-Studio"
SETTINGS_PATH = DATA_ROOT / "msst_studio_settings.json" if BUNDLED_RUNTIME.is_dir() else APP_DIR / "msst_studio_settings.json"
AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".aiff", ".aif"}
MODULES = [
    ("vocal_models", "人声分离", "把主唱与伴奏轻松分开"),
    ("kara_models", "和声分离", "听见主唱与和声的层次"),
    ("reverb_models", "混响和声分离", "整理混响、回声与延迟"),
    ("other_models", "其他模块", "降噪、修复与更多可能"),
]
COLORS = {
    "page": wx.Colour(255, 248, 235),
    "panel": wx.Colour(255, 254, 250),
    "panel_alt": wx.Colour(242, 239, 251),
    "panel_selected": wx.Colour(215, 240, 225),
    "drop": wx.Colour(226, 245, 232),
    "border": wx.Colour(221, 213, 202),
    "text": wx.Colour(65, 60, 79),
    "muted": wx.Colour(117, 108, 127),
    "accent": wx.Colour(48, 123, 100),
    "accent_dark": wx.Colour(56, 126, 107),
    "danger": wx.Colour(177, 65, 84),
}
MODULE_COLORS = [wx.Colour(220, 241, 227), wx.Colour(255, 226, 213),
                 wx.Colour(233, 224, 250), wx.Colour(255, 239, 192)]


class RoundedPanel(wx.Panel):
    """Paint smooth card edges while retaining native child controls."""
    def __init__(self, parent, color=None, radius=18):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.radius = radius
        self.outline = COLORS["border"]
        self.active = False
        self.SetBackgroundColour(color or COLORS["panel"])
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_SIZE, self._resize)

    def _resize(self, event):
        self.Refresh()
        event.Skip()

    def set_surface(self, color, active=False):
        self.SetBackgroundColour(color)
        self.active = active
        for child in self.GetChildren():
            if isinstance(child, wx.StaticText):
                child.SetBackgroundColour(color)
        self.Refresh()

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        width, height = self.GetClientSize()
        gc.SetBrush(wx.Brush(self.GetBackgroundColour()))
        gc.SetPen(wx.Pen(COLORS["accent"] if self.active else self.outline, 2 if self.active else 1))
        gc.DrawRoundedRectangle(1, 1, max(0, width - 2), max(0, height - 2), self.FromDIP(self.radius))


class RoundedButton(GenButton):
    def __init__(self, parent, label, accent=False, danger=False):
        self.accent = accent
        self.danger = danger
        self.hovered = False
        super().__init__(parent, label=label, style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_ENTER_WINDOW, self._enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._leave)

    def _enter(self, event):
        self.hovered = True
        self.Refresh()
        event.Skip()

    def _leave(self, event):
        self.hovered = False
        self.Refresh()
        event.Skip()

    def DoGetBestSize(self):
        w, h = self.GetTextExtent(self.GetLabel())
        return wx.Size(max(self.FromDIP(88), w + self.FromDIP(28)), max(self.FromDIP(40), h + self.FromDIP(16)))

    def OnPaint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        w, h = self.GetClientSize()
        fill = COLORS["accent_dark"] if self.accent else COLORS["panel_alt"]
        if self.danger:
            fill = wx.Colour(255, 231, 230)
        if self.hovered and self.IsEnabled():
            fill = fill.ChangeLightness(112 if self.accent else 96)
        if not self.IsEnabled():
            fill = wx.Colour(232, 228, 221)
        offset = 2 if not self.up else 0
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.SetBrush(wx.Brush(wx.Colour(216, 208, 195)))
        gc.DrawRoundedRectangle(1, 4, max(0, w - 2), max(0, h - 5), self.FromDIP(13))
        gc.SetBrush(wx.Brush(fill))
        gc.SetPen(wx.Pen(COLORS["accent"] if self.hasFocus else fill, 2))
        gc.DrawRoundedRectangle(1, 1 + offset, max(0, w - 2), max(0, h - 5), self.FromDIP(13))
        dc.SetFont(self.GetFont())
        ink = COLORS["danger"] if self.danger else (wx.WHITE if self.accent else COLORS["text"])
        dc.SetTextForeground(ink if self.IsEnabled() else COLORS["muted"])
        dc.DrawLabel(self.GetLabel(), wx.Rect(0, offset - 1, w, h), wx.ALIGN_CENTER)


class SoundBuddy(wx.Panel):
    """A small vector sound character, drawn sharply at any screen scale."""
    def __init__(self, parent):
        super().__init__(parent, size=parent.FromDIP((80, 80)), style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._paint)

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        w, h = self.GetClientSize()
        self.draw(gc, w, h)

    @staticmethod
    def draw(gc, w, h):
        gc.Scale(w / 80, h / 80)
        gc.SetPen(wx.Pen(COLORS["text"], 2))
        gc.SetBrush(wx.Brush(MODULE_COLORS[0]))
        gc.DrawRoundedRectangle(9, 10, 62, 61, 24)
        gc.SetPen(wx.Pen(COLORS["accent"], 5))
        for x, y in [(25, 23), (35, 17), (45, 21), (55, 26)]:
            gc.StrokeLine(x, y, x, 34)
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.SetBrush(wx.Brush(COLORS["text"]))
        gc.DrawEllipse(26, 44, 5, 7)
        gc.DrawEllipse(49, 44, 5, 7)
        gc.SetBrush(wx.Brush(wx.Colour(248, 177, 163)))
        gc.DrawEllipse(17, 51, 10, 5)
        gc.DrawEllipse(53, 51, 10, 5)
        gc.SetPen(wx.Pen(COLORS["text"], 2))
        path = gc.CreatePath()
        path.MoveToPoint(34, 54)
        path.AddCurveToPoint(37, 60, 43, 60, 46, 54)
        gc.StrokePath(path)


class OpeningSplash(wx.Frame):
    """A short, centered introduction using the original vector mascot."""
    def __init__(self):
        super().__init__(None, title="声迹", style=wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.FRAME_SHAPED | wx.BORDER_NONE)
        self.SetClientSize(self.FromDIP((320, 315)))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.started = time.monotonic()
        self.main_frame = None
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_TIMER, self._animate, self.timer)
        width, height = self.GetClientSize()
        mask = wx.Bitmap(width, height)
        dc = wx.MemoryDC(mask)
        dc.SetBackground(wx.Brush(wx.BLACK))
        dc.Clear()
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(wx.WHITE))
        unit = width / 64
        dc.DrawRoundedRectangle(round(unit), round(unit), round(62 * unit), round(61 * unit), round(24 * unit))
        dc.SelectObject(wx.NullBitmap)
        self.SetShape(wx.Region(mask, wx.BLACK))
        self.CentreOnScreen()
        self.SetTransparent(0)
        self.Show()
        self.timer.Start(16)
        wx.CallLater(600, self._prepare_main)

    def _prepare_main(self):
        # Build native controls only after the entrance animation has settled.
        # Keep the mascot visible, and resume the clock after the blocking work.
        self.timer.Stop()
        self.SetTransparent(255)
        self.main_frame = StudioFrame()
        self.started = time.monotonic() - 0.6
        self.timer.Start(16)

    def _animate(self, event):
        elapsed = time.monotonic() - self.started
        opacity = min(1.0, elapsed / 0.35)
        if elapsed > 2.15:
            opacity = max(0.0, (2.5 - elapsed) / 0.35)
        self.SetTransparent(int(255 * opacity))
        if elapsed >= 2.5 and self.main_frame is not None:
            self.timer.Stop()
            self.main_frame.Show()
            self.main_frame.Raise()
            wx.GetApp().SetTopWindow(self.main_frame)
            self.Destroy()

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(COLORS["page"]))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        width, height = self.GetClientSize()
        # Match the window silhouette to the mascot; no surrounding card or border.
        unit = width / 64
        size = 80 * unit
        gc.Translate(-8 * unit, -9 * unit)
        SoundBuddy.draw(gc, size, size)


def read_model_index():
    try:
        raw_data = MODEL_INDEX.read_bytes()
        for encoding in ("utf-8-sig", "gb18030", "gbk"):
            try:
                return json.loads(raw_data.decode(encoding))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
    except OSError:
        return {}
    return {}


class AudioDropTarget(wx.FileDropTarget):
    def __init__(self, frame):
        super().__init__()
        self.frame = frame

    def OnDropFiles(self, x, y, filenames):
        self.frame.add_audio_files(filenames)
        return True


class WaveformPanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent, size=(-1, parent.FromDIP(158)), style=wx.WANTS_CHARS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(COLORS["panel_alt"])
        self.peaks = np.array([], dtype=np.float32)
        self.media = None
        self.duration = 0
        self.position = 0
        self.accepted = False
        self.dragging = False
        self.resume_after_drag = False
        self.finished = False
        self.has_file = False
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.SetToolTip("点击波形跳转；按住鼠标拖动定位，松开后从新位置继续。")
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self._drag_begin)
        self.Bind(wx.EVT_MOTION, self._drag_move)
        self.Bind(wx.EVT_LEFT_UP, self._drag_end)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._cancel_drag)
        self.Bind(wx.EVT_CHAR_HOOK, self._key)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(), event.Skip()))
        self.Bind(wx.EVT_WINDOW_DESTROY, self._destroy)
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._tick, self.timer)

    def attach_media(self, media, play_button, on_error):
        self.media = media
        self.play_button = play_button
        self.on_error = on_error
        media.Bind(wx.media.EVT_MEDIA_FINISHED, self._finished)
        self.timer.Start(60)

    def set_load_result(self, accepted):
        self.accepted = bool(accepted)
        self._tick(None)

    @staticmethod
    def _time(milliseconds):
        seconds = max(0, int(milliseconds) // 1000)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

    def _bounds(self):
        pad = self.FromDIP(16)
        return pad, max(1, self.GetClientSize().width - 2 * pad)

    def _position_at(self, x):
        left, span = self._bounds()
        return int(max(0.0, min(1.0, (x - left) / span)) * self.duration)

    def _tick(self, event):
        if not self.media or not self.accepted or self.dragging:
            return
        length = max(0, self.media.Length())
        old = (self.duration, self.position)
        if length:
            self.duration = length
        if self.finished and self.media.GetState() != wx.media.MEDIASTATE_PLAYING:
            return
        self.finished = False
        self.position = max(0, min(self.duration, self.media.Tell()))
        if old != (self.duration, self.position):
            self.Refresh(False)

    def _finished(self, event):
        self.finished = True
        self.position = self.duration
        self.play_button.SetLabel("▶ 播放")
        self.play_button.Refresh()
        self.Refresh(False)

    def _drag_begin(self, event):
        if not self.accepted or self.duration <= 0:
            return
        self.SetFocus()
        self.resume_after_drag = self.media.GetState() == wx.media.MEDIASTATE_PLAYING
        if self.resume_after_drag:
            self.media.Pause()
        self.dragging = True
        self.CaptureMouse()
        self.position = self._position_at(event.GetX())
        self.Refresh(False)

    def _drag_move(self, event):
        if self.dragging:
            self.position = self._position_at(event.GetX())
            self.Refresh(False)
        else:
            event.Skip()

    def _drag_end(self, event):
        if not self.dragging:
            return
        target = min(self._position_at(event.GetX()), max(0, self.duration - 1))
        self.dragging = False
        if self.HasCapture():
            self.ReleaseMouse()
        actual = self.media.Seek(target)
        if actual < 0:
            self.position = max(0, self.media.Tell())
            self.on_error("当前音频无法跳转，请尝试 WAV 或 FLAC 文件")
        else:
            self.position = actual
            self.finished = False
        self._resume_drag_playback()
        self.Refresh(False)

    def _resume_drag_playback(self):
        if self.resume_after_drag:
            if self.media.Play():
                self.play_button.SetLabel("Ⅱ 暂停")
            else:
                self.play_button.SetLabel("▶ 继续")
                self.on_error("跳转后播放失败，请重新点击播放")
            self.play_button.Refresh()
        self.resume_after_drag = False

    def _cancel_drag(self, event):
        if self.dragging:
            self.dragging = False
            if self.HasCapture():
                self.ReleaseMouse()
            self.position = max(0, self.media.Tell())
            self._resume_drag_playback()
            self.Refresh(False)

    def _key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE and self.dragging:
            self._cancel_drag(event)
        else:
            event.Skip()

    def _destroy(self, event):
        if event.GetEventObject() is self:
            self.timer.Stop()
        event.Skip()

    def load_file(self, path):
        self.dragging = False
        self.resume_after_drag = False
        if self.HasCapture():
            self.ReleaseMouse()
        self.accepted = False
        self.has_file = bool(path)
        self.finished = False
        self.duration = self.position = 0
        try:
            with sf.SoundFile(path) as audio:
                self.duration = int(len(audio) / audio.samplerate * 1000)
                bucket_size = max(1, math.ceil(len(audio) / 1800))
                peaks = []
                while True:
                    block = audio.read(bucket_size, dtype="float32", always_2d=True)
                    if len(block) == 0:
                        break
                    peaks.append(float(np.max(np.abs(block))))
            self.peaks = np.asarray(peaks, dtype=np.float32)
        except Exception:
            self.peaks = np.array([], dtype=np.float32)
        self.Refresh()

    def on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetFont(self.GetFont())
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        width, height = self.GetClientSize()
        gc = wx.GraphicsContext.Create(dc)
        gc.SetPen(wx.Pen(COLORS["border"], 1))
        gc.SetBrush(wx.Brush(self.GetBackgroundColour()))
        gc.DrawRoundedRectangle(1, 1, max(0, width - 2), max(0, height - 2), self.FromDIP(16))
        left, span = self._bounds()
        top, bottom = self.FromDIP(38), height - self.FromDIP(28)
        center = (top + bottom) // 2
        progress_x = left + int(span * self.position / self.duration) if self.duration else left
        if self.has_file and self.duration:
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.SetBrush(wx.Brush(wx.Colour(221, 239, 226)))
            gc.DrawRoundedRectangle(left, top, max(0, progress_x - left), max(1, bottom - top), 4)
        gc.SetPen(wx.Pen(COLORS["border"], 1))
        gc.StrokeLine(left, center, left + span, center)
        if len(self.peaks):
            bar_width, gap = self.FromDIP(3), self.FromDIP(2)
            for x in range(left, left + span, bar_width + gap):
                start = int((x - left) / span * len(self.peaks))
                end = min(len(self.peaks), max(start + 1, int((x - left + bar_width + gap) / span * len(self.peaks))))
                peak = float(np.max(self.peaks[start:end]))
                amplitude = max(1, int(peak * max(1, bottom - top) * 0.44))
                ink = COLORS["accent"] if x <= progress_x else wx.Colour(168, 154, 195)
                gc.SetPen(wx.TRANSPARENT_PEN)
                gc.SetBrush(wx.Brush(ink))
                gc.DrawRoundedRectangle(x, center - amplitude, bar_width, amplitude * 2, 1.5)
        if self.has_file and self.duration:
            ink = wx.Colour(200, 94, 105)
            gc.SetPen(wx.Pen(ink, self.FromDIP(2)))
            gc.StrokeLine(progress_x, top, progress_x, bottom)
            gc.SetBrush(wx.Brush(ink))
            gc.DrawEllipse(progress_x - 4, top - 5, 8, 8)
        del gc
        dc.SetTextForeground(COLORS["text"])
        dc.DrawText(f"{self._time(self.position)} / {self._time(self.duration)}", left, self.FromDIP(10))
        if not self.has_file:
            dc.SetTextForeground(COLORS["muted"])
            dc.DrawLabel("导入音频后，点击或拖动波形即可定位", wx.Rect(left, top, span, max(1, bottom - top)), wx.ALIGN_CENTER)
            return
        dc.SetTextForeground(COLORS["muted"])
        hint = "松开定位 · Esc 取消" if self.dragging else "点击 / 拖动波形定位"
        hint_width = dc.GetTextExtent(hint).width
        if span > hint_width + self.FromDIP(200):
            dc.DrawText(hint, left + span - hint_width, self.FromDIP(10))
        if self.duration:
            for index in range(5):
                label = self._time(self.duration * index / 4)
                text_width = dc.GetTextExtent(label).width
                x = max(left, min(left + span - text_width, left + span * index // 4 - text_width // 2))
                dc.DrawText(label, x, bottom + self.FromDIP(5))
        if not len(self.peaks):
            dc.DrawLabel("波形暂不可用 · 加载完成后仍可点击定位", wx.Rect(left, top, span, max(1, bottom - top)), wx.ALIGN_CENTER)


class StudioFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="声迹 · MSST 音频分离工作台", size=(1240, 930), style=wx.DEFAULT_FRAME_STYLE)
        icon_path = pathlib.Path(__file__).resolve().parent / "app-icon.ico"
        if icon_path.is_file():
            self.SetIcon(wx.Icon(str(icon_path), wx.BITMAP_TYPE_ICO))
        self.SetSize(self.FromDIP((1000, 760)))
        self.SetMinSize(self.FromDIP((850, 650)))
        self.SetBackgroundColour(COLORS["page"])
        self.model_index = read_model_index()
        self.audio_paths = []
        self.result_paths = []
        self.active_module = 0
        self.current_source = None
        self.current_result = None
        self.current_result_dir = None
        self.archive_busy = False
        self.last_archive = None
        self.archive_message = "归档会保存本次任务的全部结果音频。"
        self.result_layout_width = -1
        self.staging_dir = None
        self.process = None
        self.module_settings = {}
        self.module_cards = []
        self.module_status_labels = []
        self.selection_count = None
        self.SetFont(self._make_font(10))
        self._build_ui()
        self._load_module_settings()
        self._set_module(0)
        self.Centre()
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def _panel(self, parent, color=None):
        panel = RoundedPanel(parent, color)
        panel.SetFont(self._make_font(10))
        return panel

    def _field(self, parent, choices=None, value=""):
        shell = RoundedPanel(parent, wx.WHITE, radius=12)
        shell.SetFont(self._make_font(10))
        if choices is not None:
            control = wx.adv.OwnerDrawnComboBox(shell, choices=choices, style=wx.CB_READONLY | wx.BORDER_NONE)
            control.Bind(wx.EVT_MOUSEWHEEL, lambda event, combo=control: self._on_combo_wheel(event, combo))
            if control.GetTextCtrl():
                control.GetTextCtrl().Bind(wx.EVT_MOUSEWHEEL, lambda event, combo=control: self._on_combo_wheel(event, combo))
        else:
            control = wx.TextCtrl(shell, value=value, style=wx.BORDER_NONE)
        control.SetFont(self._make_font(10))
        control.SetBackgroundColour(wx.WHITE)
        control.SetForegroundColour(COLORS["text"])
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(control, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, self.FromDIP(8))
        shell.SetSizer(row)
        return shell, control

    def _on_combo_wheel(self, event, combo):
        if combo.IsPopupShown():
            event.Skip()
            return
        # A closed dropdown must never change its value when the page scrolls.
        x, y = self.root_panel.GetViewStart()
        delta = event.GetWheelDelta() or 120
        steps = round(event.GetWheelRotation() / delta * max(1, event.GetLinesPerAction()))
        self.root_panel.Scroll(x, max(0, y - steps))

    def _make_font(self, size=10, bold=False):
        weight = wx.FONTWEIGHT_BOLD if bold else wx.FONTWEIGHT_NORMAL
        return wx.Font(wx.FontInfo(max(11, size + 1)).FaceName("Microsoft YaHei UI").Weight(weight).AntiAliased(True))

    def _label(self, parent, value, size=10, color=None, bold=False):
        control = wx.StaticText(parent, label=value)
        control.SetFont(self._make_font(size, bold))
        control.SetForegroundColour(color or COLORS["text"])
        return control

    def _button(self, parent, label, handler, accent=False, danger=False):
        button = RoundedButton(parent, label, accent, danger)
        button.SetFont(self._make_font(10, True))
        button.SetMinSize((-1, self.FromDIP(42)))
        button.SetBackgroundColour(COLORS["accent_dark"] if accent else COLORS["panel_alt"])
        button.SetForegroundColour(COLORS["danger"] if danger else (wx.WHITE if accent else COLORS["text"]))
        button.Bind(wx.EVT_BUTTON, handler)
        return button

    def _section_heading(self, parent, number, title, detail):
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self._label(parent, number, 9, COLORS["accent"], True), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 9)
        row.Add(self._label(parent, title, 12, COLORS["text"], True), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        row.Add(self._label(parent, detail, 9, COLORS["muted"]), 0, wx.ALIGN_CENTER_VERTICAL)
        return row

    def _build_ui(self):
        root = wx.ScrolledWindow(self, style=wx.VSCROLL)
        root.SetScrollRate(0, 14)
        self.root_panel = root
        root.SetBackgroundColour(COLORS["page"])
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self._build_header(root), 0, wx.EXPAND | wx.ALL, 16)
        outer.Add(self._build_import(root), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        outer.Add(self._build_player(root), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        outer.Add(self._build_modules(root), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        outer.Add(self._build_settings(root), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        outer.Add(self._build_inference_action(root), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        outer.Add(self._build_footer(root), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        self.results_panel = self._build_results(root)
        self.results_panel.Hide()
        outer.Add(self.results_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        root.SetSizer(outer)
        root.FitInside()
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(root, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

    def _build_header(self, parent):
        panel = self._panel(parent)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(SoundBuddy(panel), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 18)
        brand = wx.BoxSizer(wx.VERTICAL)
        brand.Add(self._label(panel, "声迹", 23, COLORS["accent"], True), 0)
        brand.Add(self._label(panel, "MSST 音频分离工作台", 13, COLORS["text"], True), 0, wx.TOP, 2)
        brand.Add(self._label(panel, "让每一层声音，都有自己的舞台", 9, COLORS["muted"]), 0, wx.TOP, 4)
        row.Add(brand, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 16)
        self.status_label = self._label(panel, "就绪 · 拖入音频开始", 10, COLORS["muted"])
        self.status_label.SetWindowStyleFlag(self.status_label.GetWindowStyleFlag() | wx.ST_ELLIPSIZE_END)
        self.status_label.SetMinSize((1, -1))
        row.Add(self.status_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 14)
        panel.SetSizer(row)
        return panel

    def _build_import(self, parent):
        panel = self._panel(parent, COLORS["drop"])
        panel.SetDropTarget(AudioDropTarget(self))
        row = wx.BoxSizer(wx.HORIZONTAL)
        prompt = wx.BoxSizer(wx.VERTICAL)
        prompt.Add(self._label(panel, "＋  导入音频", 13, COLORS["accent"], True), 0, wx.BOTTOM, 6)
        prompt.Add(self._label(panel, "拖放音频到此处，或浏览文件 · WAV / FLAC / MP3 / M4A / OGG / OPUS / AIFF", 9, COLORS["muted"]), 0)
        row.Add(prompt, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 14)
        add = self._button(panel, "选择文件", self.on_choose_files, accent=True)
        clear = self._button(panel, "清空列表", self.on_clear_sources)
        row.Add(add, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(clear, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        panel.SetSizer(row)
        panel.Bind(wx.EVT_LEFT_UP, self.on_choose_files)
        for child in panel.GetChildren():
            if isinstance(child, wx.StaticText):
                child.Bind(wx.EVT_LEFT_UP, self.on_choose_files)
        return panel

    def _build_player(self, parent):
        panel = self._panel(parent)
        outer = wx.BoxSizer(wx.VERTICAL)
        top = wx.BoxSizer(wx.HORIZONTAL)
        top.Add(self._label(panel, "01", 9, COLORS["accent"], True), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        top.Add(self._label(panel, "输入音频", 12, COLORS["text"], True), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        source_field, self.source_choice = self._field(panel, choices=[])
        self.source_choice.SetFont(self._make_font(10))
        self.source_choice.SetMinSize((340, -1))
        self.source_choice.Bind(wx.EVT_COMBOBOX, self.on_source_track_changed)
        top.Add(source_field, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        self.source_title = self._label(panel, "尚未载入音频", 10, COLORS["muted"])
        self.source_title.SetWindowStyleFlag(self.source_title.GetWindowStyleFlag() | wx.ST_ELLIPSIZE_END)
        self.source_title.SetMinSize((1, -1))
        top.Add(self.source_title, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        outer.Add(top, 0, wx.EXPAND | wx.ALL, 12)
        self.source_waveform = WaveformPanel(panel)
        outer.Add(self.source_waveform, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        controls = wx.BoxSizer(wx.HORIZONTAL)
        self.source_previous_button = self._button(panel, "上一曲", self.on_source_previous)
        self.source_play_button = self._button(panel, "▶ 播放", self.on_source_play_pause, accent=True)
        self.source_next_button = self._button(panel, "下一曲", self.on_source_next)
        for button in (self.source_previous_button, self.source_play_button, self.source_next_button):
            controls.Add(button, 0, wx.RIGHT, 7)
        controls.Add(self._label(panel, "音量", 9, COLORS["muted"]), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.source_volume = wx.Slider(panel, value=80, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL)
        self.source_volume.SetMinSize((130, -1))
        self.source_volume.Bind(wx.EVT_SLIDER, self.on_source_volume)
        controls.Add(self.source_volume, 0, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(controls, 0, wx.EXPAND | wx.ALL, 12)
        self.source_media = wx.media.MediaCtrl(panel, style=wx.SIMPLE_BORDER)
        self.source_media.SetSize((1, 1))
        self.source_media.Hide()
        self.source_waveform.attach_media(self.source_media, self.source_play_button, self.status_label.SetLabel)
        outer.Add(self.source_media, 0, wx.ALL, 0)
        panel.SetSizer(outer)
        return panel

    def _build_results(self, parent):
        panel = self._panel(parent)
        outer = wx.BoxSizer(wx.VERTICAL)
        padding = self.FromDIP(16)
        outer.Add(self._label(panel, "04  分离结果", 13, COLORS["accent"], True), 0, wx.ALL, padding)
        self.result_count = self._label(panel, "推理完成后显示", 9, COLORS["muted"])
        self.result_count.SetMinSize((1, -1))
        outer.Add(self.result_count, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, padding)
        result_field, self.result_choice = self._field(panel, choices=[])
        self.result_choice.SetFont(self._make_font(10))
        self.result_choice.SetMinSize((1, -1))
        result_field.SetMinSize((1, -1))
        self.result_choice.Bind(wx.EVT_COMBOBOX, self.on_result_track_changed)
        outer.Add(result_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, padding)
        self.result_title = self._label(panel, "暂无结果", 10, COLORS["muted"])
        self.result_title.SetMinSize((1, -1))
        outer.Add(self.result_title, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, padding)
        self.result_waveform = WaveformPanel(panel)
        outer.Add(self.result_waveform, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        controls = wx.WrapSizer(wx.HORIZONTAL)
        self.result_previous = self._button(panel, "上一条", self.on_result_previous)
        self.result_play = self._button(panel, "▶ 播放", self.on_result_play_pause, accent=True)
        self.result_next = self._button(panel, "下一条", self.on_result_next)
        self.result_trash = self._button(panel, "🗑 删除结果", self.on_trash, danger=True)
        self.result_archive = self._button(panel, "⇩ 一键归档", self.on_archive, accent=True)
        for button in (self.result_previous, self.result_play, self.result_next, self.result_trash, self.result_archive):
            controls.Add(button, 0, wx.RIGHT, 7)
        controls.Add(self._label(panel, "音量", 9, COLORS["muted"]), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.result_volume = wx.Slider(panel, value=80, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL)
        self.result_volume.SetMinSize((130, -1))
        self.result_volume.Bind(wx.EVT_SLIDER, self.on_result_volume)
        controls.Add(self.result_volume, 0, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(controls, 0, wx.EXPAND | wx.ALL, 12)
        self.result_media = wx.media.MediaCtrl(panel, style=wx.SIMPLE_BORDER)
        self.result_media.SetSize((1, 1))
        self.result_media.Hide()
        self.result_waveform.attach_media(self.result_media, self.result_play, self.status_label.SetLabel)
        outer.Add(self.result_media, 0, wx.ALL, 0)
        self.archive_status = self._label(panel, self.archive_message, 10, COLORS["muted"])
        self.archive_status.SetMinSize((1, -1))
        outer.Add(self.archive_status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, padding)
        self.archive_open = self._button(panel, "打开归档文件夹", self.on_open_archive)
        self.archive_open.Hide()
        outer.Add(self.archive_open, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, padding)
        panel.SetSizer(outer)
        panel.Bind(wx.EVT_SIZE, self._on_results_resize)
        return panel

    def _on_results_resize(self, event):
        width = event.GetSize().width
        event.Skip()
        if width != self.result_layout_width and width > 0:
            self.result_layout_width = width
            wx.CallAfter(self._layout_results)

    def _layout_results(self):
        if not hasattr(self, "results_panel") or self.IsBeingDeleted():
            return
        width = max(self.FromDIP(100), self.results_panel.GetClientSize().width - self.FromDIP(32))
        texts = [(self.result_count, f"本次生成 {len(self.result_paths)} 条音轨"),
                 (self.result_title, pathlib.Path(self.current_result).name if self.current_result else "暂无结果音频"),
                 (self.archive_status, self.archive_message)]
        for label, text in texts:
            # File paths may contain no spaces; wrap even these at character boundaries.
            lines = []
            for paragraph in text.split("\n"):
                line = ""
                for char in paragraph:
                    if line and label.GetTextExtent(line + char)[0] > width:
                        lines.append(line)
                        line = ""
                    line += char
                lines.append(line)
            label.SetLabel("\n".join(lines))
            label.SetToolTip(text)
        self.results_panel.InvalidateBestSize()
        self.root_panel.Layout()
        self.root_panel.FitInside()

    def _build_modules(self, parent):
        panel = self._panel(parent)
        self.modules_panel = panel
        self.module_texts = []
        self.module_layout_width = -1
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self._section_heading(panel, "02", "处理模块", "选择模型以启用模块 · 可组合处理"), 0, wx.ALL, 12)
        row = wx.GridSizer(cols=4, vgap=self.FromDIP(10), hgap=self.FromDIP(10))
        self.modules_grid = row
        for index, (_, title, description) in enumerate(MODULES):
            card = self._panel(panel, MODULE_COLORS[index])
            card.SetCursor(wx.Cursor(wx.CURSOR_HAND))
            card_sizer = wx.BoxSizer(wx.VERTICAL)
            title_label = self._label(card, title, 11, COLORS["text"], True)
            status = self._label(card, "不选择", 9, COLORS["muted"])
            self.module_status_labels.append(status)
            desc_label = self._label(card, description, 8, COLORS["muted"])
            padding = self.FromDIP(14)
            card_sizer.Add(title_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, padding)
            card_sizer.Add(desc_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, padding)
            card_sizer.Add(status, 0, wx.ALL, padding)
            self.module_texts.append((title_label, desc_label, title, description))
            card.SetSizer(card_sizer)
            card.Bind(wx.EVT_LEFT_UP, lambda event, i=index: self._set_module(i))
            title_label.Bind(wx.EVT_LEFT_UP, lambda event, i=index: self._set_module(i))
            status.Bind(wx.EVT_LEFT_UP, lambda event, i=index: self._set_module(i))
            desc_label.Bind(wx.EVT_LEFT_UP, lambda event, i=index: self._set_module(i))
            self.module_cards.append(card)
            row.Add(card, 1, wx.EXPAND)
        outer.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, self.FromDIP(12))
        self.selection_count = self._label(panel, "已配置 0 个模块", 9, COLORS["muted"])
        outer.Add(self.selection_count, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        panel.SetSizer(outer)
        panel.Bind(wx.EVT_SIZE, self._on_modules_resize)
        return panel

    def _on_modules_resize(self, event):
        width = event.GetSize().width
        event.Skip()
        if width == self.module_layout_width or width <= 0:
            return
        self.module_layout_width = width
        wx.CallAfter(self._layout_module_cards)

    def _layout_module_cards(self):
        width = self.modules_panel.GetClientSize().width
        cols = 4 if width >= self.FromDIP(1100) else 2
        self.modules_grid.SetCols(cols)
        cell_width = (width - self.FromDIP(24) - (cols - 1) * self.FromDIP(10)) // cols
        wrap_width = max(self.FromDIP(100), cell_width - self.FromDIP(32))
        for card, (title_label, description_label, title, description) in zip(self.module_cards, self.module_texts):
            title_label.SetLabel(title)
            title_label.Wrap(wrap_width)
            description_label.SetLabel(description)
            description_label.Wrap(wrap_width)
            card.InvalidateBestSize()
            card.Layout()
        self.modules_panel.InvalidateBestSize()
        self.root_panel.Layout()
        self.root_panel.FitInside()

    def _build_settings(self, parent):
        panel = self._panel(parent)
        outer = wx.BoxSizer(wx.VERTICAL)
        heading = wx.BoxSizer(wx.HORIZONTAL)
        heading.Add(self._label(panel, "03", 9, COLORS["accent"], True), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 9)
        self.module_heading = self._label(panel, "人声分离", 13, COLORS["text"], True)
        heading.Add(self.module_heading, 1, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(heading, 0, wx.EXPAND | wx.ALL, 12)

        form = wx.FlexGridSizer(rows=0, cols=3, vgap=10, hgap=12)
        form.AddGrowableCol(1, 1)
        form.Add(self._label(panel, "模型", 9, COLORS["muted"]), 0, wx.ALIGN_CENTER_VERTICAL)
        model_field, self.model_choice = self._field(panel, choices=[])
        self.model_choice.SetFont(self._make_font(10))
        self.model_choice.Bind(wx.EVT_COMBOBOX, self.on_model_selected)
        form.Add(model_field, 1, wx.EXPAND)
        form.AddSpacer(1)

        form.Add(self._label(panel, "配置文件", 9, COLORS["muted"]), 0, wx.ALIGN_CENTER_VERTICAL)
        config_field, self.config_path = self._field(panel)
        self.config_path.SetFont(self._make_font(10))
        form.Add(config_field, 1, wx.EXPAND)
        config_browse = self._button(panel, "浏览 YAML", self.on_choose_config)
        form.Add(config_browse, 0)

        form.Add(self._label(panel, "模型权重", 9, COLORS["muted"]), 0, wx.ALIGN_CENTER_VERTICAL)
        checkpoint_field, self.checkpoint_path = self._field(panel)
        self.checkpoint_path.SetFont(self._make_font(10))
        form.Add(checkpoint_field, 1, wx.EXPAND)
        checkpoint_browse = self._button(panel, "浏览权重", self.on_choose_checkpoint)
        form.Add(checkpoint_browse, 0)

        form.Add(self._label(panel, "输出目录", 9, COLORS["muted"]), 0, wx.ALIGN_CENTER_VERTICAL)
        output_field, self.output_path = self._field(panel, value=str(DATA_ROOT / "输出") if BUNDLED_RUNTIME.is_dir() else str(MSST_ROOT / "output" / "MSST-Studio"))
        self.output_path.SetFont(self._make_font(10))
        form.Add(output_field, 1, wx.EXPAND)
        output_browse = self._button(panel, "选择目录", self.on_choose_output)
        form.Add(output_browse, 0)
        outer.Add(form, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        options = wx.BoxSizer(wx.HORIZONTAL)
        self.instrumental_check = wx.CheckBox(panel, label="同时提取伴奏")
        self.instrumental_check.SetForegroundColour(COLORS["text"])
        self.tta_check = wx.CheckBox(panel, label="增强推理 TTA（耗时更长）")
        self.tta_check.SetForegroundColour(COLORS["text"])
        self.cpu_check = wx.CheckBox(panel, label="强制使用 CPU")
        self.cpu_check.SetForegroundColour(COLORS["text"])
        self.flac_check = wx.CheckBox(panel, label="输出 FLAC")
        self.flac_check.SetForegroundColour(COLORS["text"])
        for control in (self.instrumental_check, self.tta_check, self.cpu_check, self.flac_check):
            control.SetFont(self._make_font(10))
            options.Add(control, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 20)
        options.Add(self._label(panel, "GPU 编号", 9, COLORS["muted"]), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.device_id = wx.SpinCtrl(panel, min=0, max=16, initial=0, size=(64, -1))
        self.device_id.SetFont(self._make_font(10))
        options.Add(self.device_id, 0, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(options, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        panel.SetSizer(outer)
        return panel

    def _build_inference_action(self, parent):
        panel = self._panel(parent)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.inference_hint = self._label(panel, "准备就绪后运行所选模块 · 未选择模型的模块会自动跳过", 10, COLORS["muted"])
        row.Add(self.inference_hint, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 12)
        self.run_button = self._button(panel, "开始推理", self.on_run, accent=True)
        self.run_button.SetMinSize((170, 46))
        row.Add(self.run_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 10)
        panel.SetSizer(row)
        return panel

    def _build_footer(self, parent):
        panel = self._panel(parent)
        row = wx.BoxSizer(wx.VERTICAL)
        self.progress = wx.Gauge(panel, range=100, style=wx.GA_HORIZONTAL)
        self.progress.SetForegroundColour(COLORS["accent"])
        row.Add(self.progress, 0, wx.EXPAND | wx.ALL, 10)
        self.log_label = self._label(panel, "推理日志会显示在这里。", 9, COLORS["muted"])
        self.log_label.SetWindowStyleFlag(self.log_label.GetWindowStyleFlag() | wx.ST_ELLIPSIZE_END)
        self.log_label.SetMinSize((1, -1))
        row.Add(self.log_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        panel.SetSizer(row)
        return panel

    def _module_models(self, module_index):
        section = MODULES[module_index][0]
        model_map = self.model_index.get(section, {})
        available = []
        for name in model_map:
            if name == "None":
                continue
            checkpoint = MSST_ROOT / "pretrain" / name
            if checkpoint.is_file():
                available.append(name)
        return available

    def _load_module_settings(self):
        try:
            if not SETTINGS_PATH.exists() and BUNDLED_RUNTIME.is_dir():
                SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(APP_DIR / "msst_studio_settings.json", SETTINGS_PATH)
            with SETTINGS_PATH.open("r", encoding="utf-8") as file:
                saved = json.load(file)
            if isinstance(saved, dict) and "modules" in saved:
                self.module_settings = {int(key): value for key, value in saved["modules"].items()}
            else:
                self.module_settings = {int(key): value for key, value in saved.items()}
                # Old versions enabled modules with checkboxes, so leave all modules off after migration.
                for value in self.module_settings.values():
                    value["model"] = "不选择"
        except (OSError, ValueError, TypeError):
            self.module_settings = {index: {} for index in range(len(MODULES))}

    def _module_is_selected(self, index):
        model = self.module_settings.get(index, {}).get("model", "不选择")
        return model not in ("", "不选择", "自动选择可用模型")

    def _update_module_statuses(self):
        selected_count = 0
        for index, label in enumerate(self.module_status_labels):
            selected = self._module_is_selected(index)
            selected_count += int(selected)
            label.SetLabel("已启用" if selected else "不选择")
            label.SetForegroundColour(COLORS["accent"] if selected else COLORS["muted"])
            self.module_cards[index].set_surface(MODULE_COLORS[index], active=index == self.active_module)
            self.module_cards[index].Refresh()
        self.selection_count.SetLabel(f"已配置 {selected_count} 个模块")

    def _set_module(self, index):
        if index < 0 or index >= len(MODULES):
            return
        if index != self.active_module and hasattr(self, "model_choice") and hasattr(self, "module_settings"):
            self._save_active_settings()
        self.active_module = index
        self.module_heading.SetLabel(MODULES[index][1])
        saved = self.module_settings.get(index, {})
        models = self._module_models(index)
        self.model_choice.Clear()
        self.model_choice.Append("不选择")
        for model in models:
            self.model_choice.Append(model)
        selected = saved.get("model", "不选择")
        if selected == "自动选择可用模型" or selected not in self.model_choice.GetStrings():
            selected = "不选择"
        self.model_choice.SetStringSelection(selected)
        if saved and selected != "不选择":
            self.active_model_type = saved.get("model_type") or self.model_index.get("model_types", {}).get(selected, "bs_roformer")
            self.config_path.SetValue(saved.get("config", ""))
            self.checkpoint_path.SetValue(saved.get("checkpoint", ""))
            self.instrumental_check.SetValue(saved.get("instrumental", False))
            self.tta_check.SetValue(saved.get("tta", False))
            self.cpu_check.SetValue(saved.get("cpu", False))
            self.flac_check.SetValue(saved.get("flac", False))
            self.device_id.SetValue(saved.get("device_id", 0))
        else:
            self.active_model_type = ""
            self.config_path.SetValue("")
            self.checkpoint_path.SetValue("")
            self.instrumental_check.SetValue(False)
            self.tta_check.SetValue(False)
            self.cpu_check.SetValue(False)
            self.flac_check.SetValue(False)
            self.device_id.SetValue(0)
        self.Layout()
        self._update_module_statuses()

    def _apply_model(self, model):
        metadata_types = self.model_index.get("model_types", {})
        config_paths = self.model_index.get("config_paths", {})
        model_type = metadata_types.get(model, "bs_roformer")
        self.active_model_type = model_type
        checkpoint = MSST_ROOT / "pretrain" / model
        self.checkpoint_path.SetValue(str(checkpoint))
        candidates = config_paths.get(model, [])
        config = next((MSST_ROOT / item for item in candidates if (MSST_ROOT / item).is_file()), None)
        if config is None:
            tokens = model.lower().replace(".ckpt", "").replace(".pt", "").split("_")
            config_candidates = [path for path in (MSST_ROOT / "configs").glob("*.yaml") if any(token in path.name.lower() for token in tokens if len(token) > 3)]
            config = config_candidates[0] if config_candidates else None
        self.config_path.SetValue(str(config) if config else "")
        saved = self.module_settings.setdefault(self.active_module, {})
        saved["model"] = model
        saved["model_type"] = model_type
        saved["config"] = str(config) if config else ""
        saved["checkpoint"] = str(checkpoint)

    def _save_active_settings(self):
        self.module_settings[self.active_module] = {
            "model": self.model_choice.GetStringSelection(),
            "model_type": self.active_model_type,
            "config": self.config_path.GetValue().strip(),
            "checkpoint": self.checkpoint_path.GetValue().strip(),
            "instrumental": self.instrumental_check.GetValue(),
            "tta": self.tta_check.GetValue(),
            "cpu": self.cpu_check.GetValue(),
            "flac": self.flac_check.GetValue(),
            "device_id": self.device_id.GetValue(),
        }
        try:
            with SETTINGS_PATH.open("w", encoding="utf-8") as file:
                json.dump({"version": 2, "modules": self.module_settings}, file, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def on_model_selected(self, event):
        selection = self.model_choice.GetStringSelection()
        if selection == "不选择":
            self.active_model_type = ""
            self.config_path.SetValue("")
            self.checkpoint_path.SetValue("")
        else:
            self._apply_model(selection)
        self._save_active_settings()
        self._update_module_statuses()

    def on_choose_config(self, event):
        dialog = wx.FileDialog(self, "选择 MSST YAML 配置", defaultDir=str(MSST_ROOT / "configs"), wildcard="YAML 配置 (*.yaml)|*.yaml", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dialog.ShowModal() == wx.ID_OK:
            self.config_path.SetValue(dialog.GetPath())
        dialog.Destroy()

    def on_choose_checkpoint(self, event):
        dialog = wx.FileDialog(self, "选择模型权重", defaultDir=str(MSST_ROOT / "pretrain"), wildcard="模型权重 (*.ckpt;*.pt;*.th;*.bin)|*.ckpt;*.pt;*.th;*.bin|所有文件 (*.*)|*.*", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dialog.ShowModal() == wx.ID_OK:
            self.checkpoint_path.SetValue(dialog.GetPath())
        dialog.Destroy()

    def on_choose_output(self, event):
        dialog = wx.DirDialog(self, "选择推理结果目录", defaultPath=self.output_path.GetValue(), style=wx.DD_DEFAULT_STYLE)
        if dialog.ShowModal() == wx.ID_OK:
            self.output_path.SetValue(dialog.GetPath())
        dialog.Destroy()

    def on_choose_files(self, event):
        wildcard = "音频文件 (*.wav;*.flac;*.mp3;*.m4a;*.ogg;*.opus;*.aiff;*.aif)|*.wav;*.flac;*.mp3;*.m4a;*.ogg;*.opus;*.aiff;*.aif"
        dialog = wx.FileDialog(self, "选择一个或多个音频文件", wildcard=wildcard, style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST)
        if dialog.ShowModal() == wx.ID_OK:
            self.add_audio_files(dialog.GetPaths())
        dialog.Destroy()

    def add_audio_files(self, paths):
        added = 0
        for raw_path in paths:
            path = pathlib.Path(raw_path)
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            full_path = str(path.resolve())
            if full_path not in self.audio_paths:
                self.audio_paths.append(full_path)
                added += 1
        if added:
            self._refresh_source_playlist(select_last=True)
            self.status_label.SetLabel(f"已载入 {len(self.audio_paths)} 个音频文件")
        elif paths:
            self.status_label.SetLabel("没有识别到支持的音频文件")

    def on_clear_sources(self, event):
        self.audio_paths.clear()
        self._refresh_source_playlist()
        self.source_title.SetLabel("尚未载入音频")
        self.source_waveform.load_file("")
        self.source_media.Stop()
        self.status_label.SetLabel("已清空输入列表")

    def _refresh_source_playlist(self, select_last=False, selected_path=None):
        paths = self.audio_paths
        self.source_choice.Clear()
        for path in paths:
            source_path = pathlib.Path(path)
            self.source_choice.Append(f"{source_path.parent.name} / {source_path.name}")
        if not paths:
            self.current_source = None
            self.source_title.SetLabel("当前列表没有音频")
            self.source_waveform.load_file("")
            self.source_media.Stop()
            return
        index = len(paths) - 1 if select_last else 0
        if selected_path in paths:
            index = paths.index(selected_path)
        self.source_choice.SetSelection(index)
        self._load_source(paths[index])

    def on_source_track_changed(self, event):
        index = self.source_choice.GetSelection()
        paths = self.audio_paths
        if 0 <= index < len(paths):
            self._load_source(paths[index])

    def _load_source(self, path):
        self.current_source = path
        self.source_title.SetLabel(pathlib.Path(path).name)
        self.source_media.Stop()
        self.source_waveform.load_file(path)
        accepted = self.source_media.Load(path)
        self.source_waveform.set_load_result(accepted)
        if not accepted:
            self.status_label.SetLabel("音频已载入；当前系统媒体组件无法播放此编码")
        self.source_media.SetVolume(self.source_volume.GetValue() / 100.0)
        self.source_play_button.SetLabel("▶ 播放")

    def on_source_previous(self, event):
        self._step_source(-1)

    def on_source_next(self, event):
        self._step_source(1)

    def _step_source(self, direction):
        paths = self.audio_paths
        if not paths:
            return
        current = self.source_choice.GetSelection()
        self.source_choice.SetSelection((current + direction) % len(paths))
        self._load_source(paths[self.source_choice.GetSelection()])

    def on_source_play_pause(self, event):
        if not self.current_source:
            return
        if self.source_media.GetState() == wx.media.MEDIASTATE_PLAYING:
            self.source_media.Pause()
            self.source_play_button.SetLabel("▶ 继续")
        else:
            if self.result_media.GetState() == wx.media.MEDIASTATE_PLAYING:
                self.result_media.Pause()
                self.result_play.SetLabel("▶ 播放")
            if self.source_waveform.finished:
                self.source_media.Seek(0)
                self.source_waveform.finished = False
            if not self.source_media.Play():
                self.status_label.SetLabel("播放失败，请尝试 WAV 或 FLAC 文件")
            else:
                self.source_play_button.SetLabel("Ⅱ 暂停")

    def on_source_volume(self, event):
        self.source_media.SetVolume(self.source_volume.GetValue() / 100.0)

    def _refresh_results(self, selected_path=None):
        self.result_choice.Clear()
        for path in self.result_paths:
            result_path = pathlib.Path(path)
            try:
                label = str(result_path.relative_to(self.current_result_dir))
            except ValueError:
                label = result_path.name
            self.result_choice.Append(label)
        self.result_count.SetLabel(f"本次生成 {len(self.result_paths)} 条音轨")
        if not self.result_paths:
            self.current_result = None
            self.result_title.SetLabel("暂无结果音频")
            self.result_waveform.load_file("")
            self.result_media.Stop()
            self._layout_results()
            return
        index = self.result_paths.index(selected_path) if selected_path in self.result_paths else 0
        self.result_choice.SetSelection(index)
        self._load_result(self.result_paths[index])

    def on_result_track_changed(self, event):
        index = self.result_choice.GetSelection()
        if 0 <= index < len(self.result_paths):
            self._load_result(self.result_paths[index])

    def _load_result(self, path):
        self.current_result = path
        self.result_title.SetLabel(pathlib.Path(path).name)
        self._layout_results()
        self.result_media.Stop()
        self.result_waveform.load_file(path)
        accepted = self.result_media.Load(path)
        self.result_waveform.set_load_result(accepted)
        if not accepted:
            self.status_label.SetLabel("结果已载入；当前系统媒体组件无法播放此编码")
        self.result_media.SetVolume(self.result_volume.GetValue() / 100.0)
        self.result_play.SetLabel("▶ 播放")

    def on_result_previous(self, event):
        self._step_result(-1)

    def on_result_next(self, event):
        self._step_result(1)

    def _step_result(self, direction):
        if not self.result_paths:
            return
        current = self.result_choice.GetSelection()
        self.result_choice.SetSelection((current + direction) % len(self.result_paths))
        self._load_result(self.result_paths[self.result_choice.GetSelection()])

    def on_result_play_pause(self, event):
        if not self.current_result:
            return
        if self.result_media.GetState() == wx.media.MEDIASTATE_PLAYING:
            self.result_media.Pause()
            self.result_play.SetLabel("▶ 继续")
        else:
            if self.source_media.GetState() == wx.media.MEDIASTATE_PLAYING:
                self.source_media.Pause()
                self.source_play_button.SetLabel("▶ 播放")
            if self.result_waveform.finished:
                self.result_media.Seek(0)
                self.result_waveform.finished = False
            if not self.result_media.Play():
                self.status_label.SetLabel("播放失败，请尝试 WAV 或 FLAC 文件")
            else:
                self.result_play.SetLabel("Ⅱ 暂停")

    def on_result_volume(self, event):
        self.result_media.SetVolume(self.result_volume.GetValue() / 100.0)

    def on_trash(self, event):
        if not self.current_result:
            return
        path = pathlib.Path(self.current_result)
        trash_root = DATA_ROOT / "回收站" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            relative_path = path.relative_to(self.current_result_dir)
            destination = trash_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(destination))
            self.result_paths = [item for item in self.result_paths if item != self.current_result]
            self._refresh_results()
            self.status_label.SetLabel(f"结果已移入回收站：{destination}")
        except OSError as error:
            wx.MessageBox(f"无法移入回收站：\n{error}", "删除失败", wx.OK | wx.ICON_ERROR)

    def on_archive(self, event):
        if self.archive_busy:
            return
        if not self.result_paths or not self.current_result_dir or not pathlib.Path(self.current_result_dir).is_dir():
            wx.MessageBox("请先完成一次推理，再归档结果。", "没有可归档的结果", wx.OK | wx.ICON_INFORMATION)
            return
        source = pathlib.Path(self.current_result_dir)
        archive_root = DATA_ROOT / "归档"
        destination = archive_root / f"{source.name}_{datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
        count = len(self.result_paths)
        self.archive_busy = True
        self.result_archive.SetLabel("正在归档…")
        self.result_archive.Disable()
        self.result_trash.Disable()
        self.run_button.Disable()
        self.archive_message = f"正在保存 {count} 条结果音轨，请稍候…"
        self.archive_status.SetForegroundColour(COLORS["muted"])
        self._layout_results()
        threading.Thread(target=self._archive_worker, args=(source, destination, count), daemon=True).start()

    def _archive_worker(self, source, destination, count):
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination)
        except Exception as error:
            wx.CallAfter(self._archive_finished, destination, count, str(error))
        else:
            wx.CallAfter(self._archive_finished, destination, count, None)

    def _archive_finished(self, destination, count, error):
        self.archive_busy = False
        self.result_archive.SetLabel("⇩ 一键归档")
        self.result_archive.Enable()
        self.result_trash.Enable()
        self.run_button.Enable(not (self.process and self.process.poll() is None))
        if error:
            self.archive_message = f"归档失败：{error}"
            self.archive_status.SetForegroundColour(COLORS["danger"])
        else:
            self.last_archive = destination
            self.archive_message = f"已归档 {count} 条结果音轨\n保存位置：{destination}"
            self.archive_status.SetForegroundColour(COLORS["accent"])
            self.archive_open.Show()
        self._layout_results()
        wx.MessageBox(self.archive_message, "归档失败" if error else "归档完成", wx.OK | (wx.ICON_ERROR if error else wx.ICON_INFORMATION), parent=self)

    def on_open_archive(self, event):
        if self.last_archive:
            try:
                os.startfile(str(self.last_archive))
            except OSError as error:
                wx.MessageBox(f"无法打开归档目录：\n{error}", "打开失败", wx.OK | wx.ICON_ERROR, parent=self)

    def on_run(self, event):
        if self.archive_busy:
            return
        if self.process and self.process.poll() is None:
            wx.MessageBox("当前推理任务尚未结束。", "正在推理", wx.OK | wx.ICON_INFORMATION)
            return
        if not self.audio_paths:
            wx.MessageBox("先拖入或选择要处理的音频文件。", "缺少输入音频", wx.OK | wx.ICON_WARNING)
            return
        self._save_active_settings()
        selected = [index for index in range(len(MODULES)) if self._module_is_selected(index)]
        if not selected:
            wx.MessageBox("请至少在一个模块设置中选择具体模型。", "尚未选择模块", wx.OK | wx.ICON_INFORMATION)
            return
        if not PYTHON_EXE.is_file() or not INFERENCE_SCRIPT.is_file():
            wx.MessageBox(f"没有找到 MSST 推理环境：\n{MSST_ROOT}", "MSST 目录不可用", wx.OK | wx.ICON_ERROR)
            return
        invalid = []
        for index in selected:
            settings = self.module_settings.get(index, {})
            model = settings.get("model", "不选择")
            config = pathlib.Path(settings.get("config", ""))
            checkpoint = pathlib.Path(settings.get("checkpoint", ""))
            if model in ("", "不选择", "自动选择可用模型"):
                invalid.append(f"{MODULES[index][1]}：请选择模型")
            if not config.is_absolute():
                config = MSST_ROOT / config
            if not config.is_file():
                invalid.append(f"{MODULES[index][1]}：请选择有效 YAML 配置")
            if not checkpoint.is_absolute():
                checkpoint = MSST_ROOT / checkpoint
            if not checkpoint.is_file():
                invalid.append(f"{MODULES[index][1]}：请选择有效模型权重")
            if not settings.get("model_type"):
                invalid.append(f"{MODULES[index][1]}：请选择模型类型")
        if invalid:
            wx.MessageBox("\n".join(invalid), "请完善已启用模块的推理设置", wx.OK | wx.ICON_WARNING)
            return
        output_value = self.output_path.GetValue().strip()
        if not output_value:
            wx.MessageBox("请指定推理结果目录。", "推理设置不完整", wx.OK | wx.ICON_WARNING)
            return
        self.results_panel.Hide()
        self.result_paths = []
        self.root_panel.Layout()
        self.root_panel.FitInside()
        output_root = pathlib.Path(output_value)
        self.staging_dir = pathlib.Path(tempfile.mkdtemp(prefix="msst_studio_input_"))
        for path in self.audio_paths:
            filename = pathlib.Path(path).name
            destination = self.staging_dir / filename
            stem = pathlib.Path(filename).stem
            suffix = pathlib.Path(filename).suffix
            number = 2
            while destination.exists():
                destination = self.staging_dir / f"{stem}_{number}{suffix}"
                number += 1
            shutil.copy2(path, destination)
        job_stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        batch_dir = output_root / job_stamp
        jobs = []
        for index in selected:
            settings = self.module_settings[index]
            config = pathlib.Path(settings["config"])
            checkpoint = pathlib.Path(settings["checkpoint"])
            if not config.is_absolute():
                config = MSST_ROOT / config
            if not checkpoint.is_absolute():
                checkpoint = MSST_ROOT / checkpoint
            module_name = MODULES[index][1]
            module_output = batch_dir / module_name
            module_output.mkdir(parents=True, exist_ok=True)
            command = [
                str(PYTHON_EXE), str(INFERENCE_SCRIPT),
                "--model_type", settings["model_type"],
                "--config_path", str(config),
                "--start_check_point", str(checkpoint),
                "--input_folder", str(self.staging_dir),
                "--store_dir", str(module_output),
                "--device_ids", str(settings.get("device_id", 0)),
            ]
            if settings.get("instrumental"):
                command.append("--extract_instrumental")
            if settings.get("tta"):
                command.append("--use_tta")
            if settings.get("cpu"):
                command.append("--force_cpu")
            if settings.get("flac"):
                command.extend(["--flac_file", "--pcm_type", "PCM_24"])
            jobs.append((module_name, command))
        self.current_result_dir = str(batch_dir)
        self.run_button.Disable()
        self.progress.Pulse()
        module_names = "、".join(MODULES[index][1] for index in selected)
        self.status_label.SetLabel(f"准备处理 {len(self.audio_paths)} 个音频 · {len(selected)} 个模块")
        self.log_label.SetLabel(f"依次运行：{module_names}")
        threading.Thread(target=self._run_process, args=(jobs, batch_dir), daemon=True).start()

    def _run_process(self, jobs, batch_dir):
        return_code = 0
        failed_module = ""
        messages = []
        try:
            for module_name, command in jobs:
                failed_module = module_name
                wx.CallAfter(self.status_label.SetLabel, f"正在运行模块：{module_name}")
                child_env = os.environ.copy()
                for key in ("PYTHONHOME", "PYTHONPATH"):
                    child_env.pop(key, None)
                child_env["PYTHONUTF8"] = "1"
                child_env["PATH"] = os.pathsep.join([str(MSST_ROOT / "env"), str(MSST_ROOT / "env" / "Library" / "bin"), str(MSST_ROOT / "env" / "Scripts"), child_env.get("PATH", "")])
                frozen_windows = sys.platform == "win32" and getattr(sys, "frozen", False)
                if frozen_windows:
                    ctypes.windll.kernel32.SetDllDirectoryW(None)
                try:
                    process = subprocess.Popen(command, cwd=str(MSST_ROOT), env=child_env, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
                finally:
                    if frozen_windows:
                        ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS)
                self.process = process
                for line in process.stdout:
                    messages.append(line.rstrip())
                    if len(messages) > 5:
                        messages = messages[-5:]
                    wx.CallAfter(self.log_label.SetLabel, f"[{module_name}]\n" + "\n".join(messages))
                return_code = process.wait()
                if return_code != 0:
                    break
            output_files = [str(path) for path in batch_dir.rglob("*") if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS]
            wx.CallAfter(self._process_finished, return_code, output_files, str(batch_dir), failed_module)
        except Exception as error:
            wx.CallAfter(self._process_failed, str(error))

    def _process_finished(self, return_code, output_files, batch_dir, failed_module):
        self.last_archive = None
        self.archive_message = "本次结果尚未归档，点击“一键归档”保存全部结果。"
        self.archive_status.SetForegroundColour(COLORS["muted"])
        self.archive_open.Hide()
        self.run_button.Enable()
        if self.staging_dir:
            shutil.rmtree(self.staging_dir, ignore_errors=True)
            self.staging_dir = None
        self.progress.SetValue(100 if return_code == 0 else 0)
        self.result_paths = sorted(output_files)
        self.current_result_dir = batch_dir
        self.results_panel.Show(bool(self.result_paths))
        self.root_panel.FitInside()
        self.root_panel.Layout()
        if self.result_paths:
            self._refresh_results()
            wx.CallAfter(self.root_panel.Scroll, 0, self.root_panel.GetScrollRange(wx.VERTICAL))
        if return_code == 0:
            self.status_label.SetLabel(f"推理完成 · {len(self.result_paths)} 条结果音轨")
            self.log_label.SetLabel("结果已显示在窗口底部，可试听、切换、删除或归档。")
        else:
            self.status_label.SetLabel(f"{failed_module} 推理失败，退出代码 {return_code}")
            self.log_label.SetLabel(f"在 {failed_module} 模块遇到错误；已完成模块的结果仍显示在窗口底部。")

    def _process_failed(self, message):
        self.run_button.Enable()
        if self.staging_dir:
            shutil.rmtree(self.staging_dir, ignore_errors=True)
            self.staging_dir = None
        self.progress.SetValue(0)
        self.status_label.SetLabel("推理启动失败")
        self.log_label.SetLabel(message)
        wx.MessageBox(f"推理启动失败：\n{message}", "MSST 推理错误", wx.OK | wx.ICON_ERROR)

    def on_close(self, event):
        if self.archive_busy and event.CanVeto():
            event.Veto()
            wx.MessageBox("正在保存归档，请等待归档完成后再关闭。", "正在归档", wx.OK | wx.ICON_INFORMATION, parent=self)
            return
        self._save_active_settings()
        if self.process and self.process.poll() is None:
            self.process.terminate()
        event.Skip()


if __name__ == "__main__":
    checking_startup = "--startup-check" in sys.argv
    startup_errors = []
    if checking_startup:
        import traceback
        def startup_exception(exc_type, exc_value, exc_tb):
            startup_errors.append("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
            (APP_DIR / "startup-check.json").write_text(json.dumps({"ok": False, "errors": startup_errors}, ensure_ascii=False), encoding="utf-8")
        sys.excepthook = startup_exception
    app = wx.App(False)
    if checking_startup:
        frame = StudioFrame()
        frame.Show()
        def finish_startup_check():
            report = {"ok": frame.IsShown() and not startup_errors, "title": frame.GetTitle(), "errors": startup_errors}
            (APP_DIR / "startup-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            frame.Destroy()
            app.ExitMainLoop()
        wx.CallLater(1500, finish_startup_check)
    else:
        splash = OpeningSplash()
    app.MainLoop()

