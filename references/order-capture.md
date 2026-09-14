# 携程订单详情自动采集

当携程不能下载订单详情、但用户可以在网页端查询订单时，使用 `scripts/ctrip_order_capture.py`。脚本只进行订单查询、打开详情、展开内容和保存页面，不处理取消、退订、支付或变更。

## 准备订单清单

复制 `assets/order-capture-template.csv`，按消费明细填写：

- `seq`：报销明细序号；
- `order_no`：携程订单号；
- `person`：入住人，可留空；
- `skip`：按业务规则空开时填 `空开`，否则留空。

同一订单号出现多次时，脚本只抓取一次，并在采集清单中指向第一次出现的序号。

## 首次登录

```bash
python3 scripts/ctrip_order_capture.py login
```

脚本会打开独立 Chrome 窗口。用户亲自完成账号、短信验证码、扫码或验证码登录，然后进入“我的订单”页面并复制地址栏网址。不得将密码、验证码或浏览器资料写入 Skill 或 Git 仓库。

## 批量抓取

```bash
python3 scripts/ctrip_order_capture.py capture \
  --input "/绝对路径/orders.csv" \
  --orders-url "登录后的我的订单页面网址" \
  --output-dir "/仓库外/携程订单详情"
```

每个成功订单输出：

- `序号_订单号_入住人.pdf`；
- `序号_订单号_入住人.png`（整页截图）；
- `capture_manifest.csv`（成功、复用、空开及失败状态）。

## 页面改版与失败处理

- `login_required`：登录已失效，重新运行 `login`。
- `selector_needed`：找不到订单号输入框。先在浏览器确认已到订单列表页，再用 `--search-selector` 指定输入框。
- `not_found`：查询结果没有该订单号；核对订单号、账号权限和订单状态。
- `verification_failed`：进入页面后没有再次看到订单号，不将其视为有效证据。
- `error` 或 `cli_error`：保留 `_失败现场.png`，根据画面调整 `--search-selector`、`--submit-selector` 或 `--ready-selector`。

页面结构未知时只做一次小批量测试。先用1—2个订单确认截图完整、PDF可读、订单号一致，再处理全月订单。验证码或风控提示必须交给用户处理，不能绕过。

## 安全要求

- 订单输出和独立浏览器资料必须位于 Git 仓库之外；脚本会拒绝向 Git 仓库内写入订单证据。
- 不上传 Cookies、登录状态、订单 PDF、截图或人员信息。
- 完成报销资料包后，按公司的档案保管制度处理本地采集文件。
