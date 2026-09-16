# 携程报销资料编排 Skill

一个用于整理中国企业携程差旅报销整套资料的 Codex Skill。它以费用划分表为主控顺序，完成机票、住宿费用分摊，核验出差或接待审批、住宿标准、订单详情、退票说明和发票，并按公司及明细序号编排 PDF。

默认只扫描用户已下载的本地资料，不登录携程、不代为下载或打印订单。网页逐单打印只在用户对当前任务再次明确要求时启用。

## 安装

将本仓库目录复制到：

```text
~/.codex/skills/ctrip-reimbursement-packet-organizer
```

## 使用

在 Codex 中上传费用划分表、用款申请、携程消费明细、OA 单据、订单详情和发票，然后输入：

```text
使用 $ctrip-reimbursement-packet-organizer 按费用划分表顺序核验并整理这套携程报销资料。
```

## 内容

- `SKILL.md`：Skill 入口与完整工作流
- `references/rules.md`：费用分摊、审批、住宿超标、订单及发票规则
- `references/order-capture.md`：携程订单详情逐单打印 PDF 说明
- `scripts/ctrip_order_capture.py`：按序号和订单号逐单打印独立 PDF
- `assets/order-capture-template.csv`：订单打印清单模板
- `assets/费用划分表版式模板.xlsx`：已去除实际月份、公司、金额和序号区间的空白模板
- `agents/openai.yaml`：Codex 界面元数据

报销单据可能包含敏感信息。Skill 要求仅在本地处理原始材料，不将报销票据或人员资料上传至外部服务。
