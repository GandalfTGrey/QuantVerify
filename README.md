# QuantVerify

QuantVerify 是一个以实验为中心、强调可复现性和防止研究偏差的策略研究实验室。

当前处于 Stage 1（Signal Research）的基础阶段。系统先建立稳定的领域契约、实验身份和数据谱系，再接入批量回测、稳健性检验及可视化。交易执行、仿真和实盘属于 Stage 2。

## 当前实现

- 严格的核心领域模型；
- 确定性的实验 ID 与运行 ID；
- 信号时点、执行时点和交易成本假设的显式配置；
- 面向数据、策略、研究引擎和结果存储的端口协议；
- 单元测试覆盖身份稳定性和关键校验规则。

## 本地开发

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,research,market-data]'
pytest
```

架构、审查结论和实施节奏分别见：

- [项目架构](docs/PROJECT_ARCHITECTURE.md)
- [架构审查](docs/ARCHITECTURE_REVIEW.md)
- [实施计划](docs/IMPLEMENTATION_PLAN.md)
- [数据与回测完整性守则](docs/BACKTEST_DATA_INTEGRITY.md)
- [策略研究协议](docs/STRATEGY_RESEARCH_PROTOCOL.md)
- [策略宇宙](docs/STRATEGY_UNIVERSE.md)
- [M1 研究范围](docs/M1_RESEARCH_SCOPE.md)
- [贡献者协作协议](docs/COLLABORATION_PROTOCOL.md)
- [协作范围与并行交付地图](docs/COLLABORATION_SCOPE.md)
- [Argus 协作与研究工程守则](docs/ARGUS_COLLABORATION_CHARTER.md)
- [Architecture Decision Records](docs/adr/README.md)
