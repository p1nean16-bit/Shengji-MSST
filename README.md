# APine · 声迹音频工作台

![程序图标](app-icon.png)

面向 Windows 的音频分离桌面程序，采用圆角卡通界面，支持拖拽文件、波形定位试听和结果归档。

## 下载与安装

前往 [V1 下载页面](https://github.com/p1nean16-bit/APine/releases/tag/V1)，下载 `Setup.exe` 和**所有** `Setup-*.bin` 文件。

1. 把安装 EXE 和所有 BIN 分卷放在同一文件夹。
2. 双击 `Setup.exe`，选择安装目录并按向导完成安装。
3. 使用桌面快捷方式启动程序。

不需要另外安装 Python 或下载基础模型。GitHub 自动生成的 `Source code` 压缩包包含源码，不是安装程序。

## 功能

- 点击选取或拖入多个音频文件，切换曲目并调节音量。
- 输入与分离结果分别试听，点击波形或拖动播放位置。
- 人声分离、和声分离、混响和声分离、其他模块可分别选择模型；“不选择”跳过该模块。
- 统一开始推理，结果在底部显示，支持切换、删除及一键归档。
- 屏幕中央的图标开场动画，默认普通窗口启动。

## V1 包含内容

离线安装包包含完整推理环境和一个基础人声/伴奏模型 `becruily_deux.ckpt`。其他模型未包含，可自行选择相应的 YAML 配置与权重。默认使用 CPU；具有适用 NVIDIA 显卡与驱动的电脑可尝试取消“强制使用 CPU”。

适用 Windows 10/11 64 位，建议预留约 11 GB 安装空间。CPU 推理可能耗时较长。本版本已完成打包，尚未在其他电脑上实测。

输出、归档、回收站及个人设置默认位于 `%LOCALAPPDATA%\MSST-Studio`。卸载时保留这些个人数据。

## 从源码运行

使用配置好依赖的 MSST 推理环境运行 `msst_studio.py`。默认从源码旁的 `runtime` 目录读取 `inference.py`、`model_config_zh.json`、`env/python.exe`、`configs`、`models`、`utils` 和 `pretrain`；也可以用环境变量 `MSST_ROOT` 指定完整的 MSST 项目目录。

源码主要依赖 Python、wxPython、NumPy、soundfile；推理还需要原 MSST 的模型依赖。普通用户请使用上方的离线安装包。

## 致谢与反馈

推理功能基于 [Music Source Separation Training](https://github.com/ZFTurbo/Music-Source-Separation-Training) 及本地 MSST-GUI 运行环境。安装目录 `runtime/LICENSE` 保留上游代码许可证；模型及第三方依赖遵循各自许可。

遇到问题可在 [Issues](https://github.com/p1nean16-bit/APine/issues) 描述复现步骤和错误信息。
