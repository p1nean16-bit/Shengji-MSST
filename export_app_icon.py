"""Export the original in-app vector character, never a screenshot."""
from pathlib import Path
import wx
from PIL import Image
from msst_studio import SoundBuddy

root = Path(__file__).resolve().parent
app = wx.App(False)
size = 512
pixels = wx.Image(size, size)
pixels.SetAlpha(bytes(size * size))
bitmap = wx.Bitmap(pixels)
dc = wx.MemoryDC(bitmap)
gc = wx.GraphicsContext.Create(dc)
SoundBuddy.draw(gc, size, size)
del gc
dc.SelectObject(wx.NullBitmap)
bitmap.SaveFile(str(root / 'app-icon.png'), wx.BITMAP_TYPE_PNG)
Image.open(root / 'app-icon.png').save(root / 'app-icon.ico', format='ICO', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
