# Windows x64 硬件完整流程

本文是 YareLampGo V2.0 在 Windows x64 上从零开始装机、编号、校准和首次启动的完整顺序。
如果你只想先体验软件，可以跳过本文，执行 `uv run lampgo run --web --no-hw`。

## 0. 安全边界

开始前请准备：

- Windows 10/11 x64、Python 3.12+ 和 PowerShell。
- 一个可断开的 12V 电源开关。
- 万用表。
- 空旷、不会夹手或碰撞的机械臂运动范围。

必须遵守：

- 改舵机线、写舵机 ID 或切换舵机时，先断开 12V。
- 写 ID 时总线上只能有一颗舵机。
- 新板先拆下 S3、C6、LED 和功放，确认 +5V 后再装逻辑模块。
- 不要在未确认防反灌设计前，同时用 USB 和外部 +5V 给同一模块供电。
- 第一次真实运动前，扶稳机构并准备随时急停或断开 12V。

## 1. 安装软件

在 PowerShell 中进入项目根目录：

```powershell
Set-Location 'C:\Users\你的用户名\Downloads\YareLampGo-main'
powershell -ExecutionPolicy Bypass -File .\install.ps1 --dev
```

验证安装：

```powershell
uv run python --version
uv run lampgo --help
uv run pytest -q
```

如果 `uv` 没有加入当前 PowerShell 的 PATH，可以直接使用项目虚拟环境：

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\lampgo.exe --help
```

## 2. 自动检测 COM 串口

先运行只读探测：

```powershell
uv run lampgo detect
```

探测会扫描：

- Windows `COM` 串口。
- Feetech 电机总线。
- ESP32/LED 串口。
- DirectShow 摄像头。
- 麦克风输入设备。

Windows 的蓝牙虚拟串口（`BTHENUM`，常见于“蓝牙链接上的标准串行”）默认跳过，因为它们可能在打开时长时间阻塞；如果你的电机适配器确实使用蓝牙，仍可用 `--port COMx` 显式指定。

如果当前只想判断电机适配器的 COM 口、不等待摄像头或麦克风探测，可以直接运行电机专用路径：

```powershell
uv run lampgo setup-motors --auto-detect
```

它会在真正写入 ID 前先完成端口选择，并且仍会要求每次只接一颗舵机。

配置舵机 ID 时，默认会自动选择电机串口：

```powershell
uv run lampgo setup-motors
```

端口选择优先级如下：

1. 命令行显式指定的 `--port COM5`。
2. 已保存的 `device.motor_port` 配置。
3. 自动扫描并探测 Feetech 响应。
4. 只有一个 COM 口但半双工探测不确定时，使用该唯一端口作为候选。

如果想忽略旧配置、强制重新扫描：

```powershell
uv run lampgo setup-motors --auto-detect
```

`--rescan` 是同义写法。扫描和校准也支持强制重扫：

```powershell
uv run lampgo scan-motors --auto-detect --ids 1-5
uv run lampgo ping --auto-detect
uv run lampgo calibrate --auto-detect --id AL02
```

如果有多个 COM 口且程序无法安全区分，`setup-motors` 会列出候选并要求你选择。自动检测不会在这种情况下盲目写 ID；也可以人工确认后执行：

```powershell
uv run lampgo setup-motors --port COM5
```

## 3. 给五颗舵机写入 ID

对应关系：

| 机械位置 | 程序名称 | 目标 ID |
| --- | --- | ---: |
| 底座水平旋转 | `base_yaw` | 1 |
| 底座俯仰 | `base_pitch` | 2 |
| 肘部俯仰 | `elbow_pitch` | 3 |
| 手腕滚转 | `wrist_roll` | 4 |
| 手腕俯仰 | `wrist_pitch` | 5 |

启动完整编号向导：

```powershell
uv run lampgo setup-motors --auto-detect
```

每个提示都执行以下顺序：

1. 断开 12V。
2. 只连接当前提示位置的一颗舵机。
3. 确认没有第二颗舵机共用总线。
4. 恢复供电并按 ENTER。
5. 等待写入成功。
6. 再次断开 12V，才允许切换下一颗舵机。

不要为每颗舵机重新启动一次五舵机向导。

## 4. 编号后的只读验证

五颗舵机全部接回总线后，执行：

```powershell
uv run lampgo scan-motors --auto-detect --ids 1-5
uv run lampgo ping --auto-detect
```

必须满足：

- ID 1、2、3、4、5 各有一个响应。
- 没有重复 ID。
- 没有间歇性掉线。
- 型号和通信状态正常。

缺失、重复或不稳定时，不要进入校准。

## 5. 烧录 S3 和 C6 固件

固件位于独立的 `YareLampGo_esp32` 仓库，烧录前以该仓库当前 README 和脚本为准。

Windows 用户可以使用 Arduino IDE：

- S3 选择 `XIAO_ESP32S3`。
- 按固件仓库要求启用 OPI PSRAM。
- C6 选择 ESP32-C6，并使用 8MB Flash 配置。
- S3 和 C6 使用不同的 COM 口。

`--erase` 只用于首次安装或明确的恢复操作。擦除会清除旧 Wi-Fi 和设备绑定。

烧录成功后还要验证：

- S3 能启动。
- 摄像头能工作。
- 麦克风和扬声器链路能工作。
- LED 能响应。
- S3/C6 UART 通信正常。
- Wi-Fi 能连接。

烧录命令成功不等于整机链路已经通过。

## 6. 断电组装和电气检查

全程断开 12V 和 USB，按 V2.0 组装文档完成机械结构。检查：

- 舵机线不会被外壳夹住、拉紧或磨损。
- S3 GPIO43 TX → C6 RX。
- S3 GPIO44 RX ← C6 TX。
- LED U3 针序与 PCB 丝印方向一致。
- 12V 舵机侧和 +5V 逻辑侧没有接反。
- 所有逻辑地共地。
- 紧固件、热熔嵌件和连接器已经固定。
- 没有松动金属可能短路 PCB。

## 7. 首次上电

1. 拆下 S3、C6、LED 和功放，只给电源模块接入 12V。
2. 用万用表确认 +5V 对 GND 的电压和极性。
3. 断电后安装逻辑模块。
4. 分别通过 USB 确认 S3/C6 可以启动。
5. 确认机械臂远离硬限位，运动范围无人无物。
6. 接入舵机 12V。
7. 先只做只读检测：

```powershell
uv run lampgo detect
uv run lampgo scan-motors --auto-detect --ids 1-5
uv run lampgo ping --auto-detect
```

五颗舵机稳定在线后，才进入校准。

## 8. 备份并校准

先确认当前 Lamp ID，例如 `AL02`。如果已有同名校准文件，先备份到用户目录，不要直接覆盖：

```powershell
$backup = Join-Path $env:USERPROFILE ('.lampgo\backups\calibration\' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path $backup | Out-Null
Copy-Item .\assets\calibration\* $backup -Recurse -Force
```

从项目根目录运行：

```powershell
uv run lampgo calibrate --auto-detect --id AL02
```

也可以明确指定端口：

```powershell
uv run lampgo calibrate --port COM5 --id AL02
```

校准前必须：

- 清空运动范围。
- 扶稳机构。
- 远离机械硬限位。
- 准备急停和 12V 断电。

## 9. 配置和启动真实台灯

使用向导配置电机、LED、摄像头和麦克风：

```powershell
uv run lampgo onboard
```

硬件步骤会再次显示自动探测到的 COM 口和推荐端口。确认无误后保存。

第一次启动建议跳过自动回零，先确认服务和状态：

```powershell
uv run lampgo run --web --no-home
```

如果向导没有保存端口，再显式追加 `--motor-port COM5`，把 `COM5` 换成实际端口。

另开 PowerShell：

```powershell
uv run lampgo status
uv run lampgo ping --auto-detect
uv run lampgo skills
```

确认 `hal_connected`、`hardware_present` 和电机状态正常后，再测试自动回零。浏览器打开：

```text
http://127.0.0.1:8420
```

## 10. 第一次真实动作

一次只测一个关节、小角度、低速度：

```powershell
uv run lampgo move base_yaw=3 --velocity 15
uv run lampgo invoke return_safe
```

确认方向、幅度、线束和噪声都正常后，再逐个测试其他关节：

```powershell
uv run lampgo move base_pitch=3 --velocity 15
uv run lampgo invoke return_safe

uv run lampgo move elbow_pitch=3 --velocity 15
uv run lampgo invoke return_safe

uv run lampgo move wrist_roll=3 --velocity 15
uv run lampgo invoke return_safe

uv run lampgo move wrist_pitch=3 --velocity 15
uv run lampgo invoke return_safe
```

出现错误方向、卡顿、异响、发热、线材拉紧或接近限位时：

```powershell
uv run lampgo estop
```

如果软件急停不够快，直接断开 12V。

## 11. 外设验收

按实际配置逐项验收：

- LED：`uv run lampgo invoke set_expression expression=heart`
- 时钟：`uv run lampgo invoke show_clock`
- 摄像头：Web 设置中选择 `0`、`1` 等 DirectShow 索引并查看预览。
- 麦克风：`uv run lampgo detect` 查看默认输入设备。
- 音乐处理链路：`uv run lampgo invoke dance_to_music duration=5 source=synthetic amplitude=0.1 led=false`
- Windows 系统音频：启用 Stereo Mix 或虚拟回环输入后使用 `source=system`。

## 12. 退出和清理

优先在服务窗口按 `Ctrl+C`。确认已停止后，如需释放扭矩：

```powershell
uv run lampgo clear
```

如果不希望清理其他相关进程，只做安全的无硬件清理：

```powershell
uv run lampgo clear --skip-kill --skip-release
```

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 只有一个 COM 口但提示探测不确定 | 程序会自动采用唯一端口；确认电机供电后继续。 |
| 蓝牙 COM 没有出现在候选列表 | `BTHENUM` 虚拟口默认跳过；确认适配器类型后使用 `--port COMx`。 |
| 有多个 COM 口且没有自动选中 | 在交互提示中选择电机适配器，或使用 `--port COM5`。 |
| 旧配置指向错误 COM 口 | 使用 `--auto-detect` 或删除/修改 `device.motor_port`。 |
| `Access denied` | 关闭 Arduino 串口监视器、串口调试工具和其他 LampGo 进程。 |
| 五颗舵机都无响应 | 检查 12V、总线数据线、半双工适配器方向和波特率。 |
| 摄像头无法打开 | 关闭 Teams/微信/Zoom，依次尝试摄像头索引 `0`、`1`。 |
| 音乐模式没有系统声音 | 启用 Stereo Mix 或配置 Windows 虚拟回环输入。 |
