# 商圈客流设备重叠与人数区间估计

面向商场经营数据分析员，处理采信、判定、核算、复核与归档。

## 启动

```bash
docker compose up --build -d
```

访问 http://localhost:18251 。初次启动自动运行脏样例，可切换 clean.csv 与 legacy.csv。顶部“运行批次”会重新计算，同源输入复用批次。

## 业务模块

- 设备采信：`/m1_ingest`、`/api/m1_ingest`
- 区域映射：`/m2_mapping`、`/api/m2_mapping`
- 观测分桶：`/m3_versions`、`/api/m3_versions`
- 重叠约束：`/m4_segments`、`/api/m4_segments`
- 人数估界：`/m5_calculate`、`/api/m5_calculate`
- 日汇对账：`/m6_reconcile`、`/api/m6_reconcile`
- 报告归档：`/m7_archive`、`/api/m7_archive`

## 核心规则

无法识别个人时只输出满足区域交集约束的人数上下界；矛盾观测隔离而非伪造精确人数。完整数值、边界和异常定义见 `docs/DATA-DICTIONARY.md`。

闸机日结总量是**佐证而非正式约束**：落在客次区间内仅标记“佐证一致”，正式结果始终是区间；越出区间则总量与区间同时保留、批次转待核对，不封存、不可复核通过。对账页面（M6）与封存资料（M7）同判断。小时补录只重算补录行所在UTC小时，越界影响以 RECOMPUTE 拒绝；同批重跑不新增对账版本，封存切换失败保留旧版且不丢记录。

## 验证

```bash
docker compose exec -T app pytest -q
docker compose config --quiet
```

原始样例在 `sample_data/`。测试在 `tests/`。封存文件是单份CSV，含运行清单、计算证据、隔离原因与对账。复核需提交当前版本，陈旧复核返回409。

## 数据与限制

SQLite保存在records命名卷，普通重启与构建不会清除。确认可丢弃本项目数据后，运行 `docker compose down -v` 再启动可重置。单文件上限2MB；不接入外部业务系统；历史规则由本项目样例定义，不代表实际行业标准。
