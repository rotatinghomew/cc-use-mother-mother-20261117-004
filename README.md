# LabLedger 科研数据复现审查台

LabLedger 面向需要核对重复实验测量结果的科研团队。它将每轮输入的 SHA-256 摘要、校准上下文、质控结论、校正后读数和导入审计记录保存在本地。未通过质控的轮次仍可复查，但不会进入跨轮估计。

## 运行演示

需要 Python 3.11 或更新版本。在项目根目录执行：

```sh
PYTHONPATH=src python -m labledger.demo
```

演示只读取 `fixtures/` 中的本地合成数据，并在临时目录创建 SQLite 数据库。

## 命令示例

```sh
PYTHONPATH=src python -m labledger --database evidence.sqlite3 import fixtures/run-a.json
PYTHONPATH=src python -m labledger --database evidence.sqlite3 preview fixtures/run-b.json
PYTHONPATH=src python -m labledger --database evidence.sqlite3 batch fixtures/run-a.json fixtures/run-b.json
PYTHONPATH=src python -m labledger --database evidence.sqlite3 manifest fixtures/manifest.json
PYTHONPATH=src python -m labledger --database evidence.sqlite3 preview-batch fixtures/run-a.json fixtures/run-b.json
PYTHONPATH=src python -m labledger --database evidence.sqlite3 report demo-study --tolerance 0.15
PYTHONPATH=src python -m labledger --database evidence.sqlite3 findings demo-study round-a
PYTHONPATH=src python -m labledger --database evidence.sqlite3 diagnostics demo-study round-a
PYTHONPATH=src python -m labledger --database evidence.sqlite3 provenance demo-study
PYTHONPATH=src python -m labledger --database evidence.sqlite3 replay demo-study round-a
PYTHONPATH=src python -m labledger --database evidence.sqlite3 export demo-study evidence.json --format json
PYTHONPATH=src python -m labledger --database evidence.sqlite3 verify-export evidence.json
PYTHONPATH=src python -m labledger --database evidence.sqlite3 studies
PYTHONPATH=src python -m labledger --database evidence.sqlite3 verify-audit demo-study
PYTHONPATH=src python -m labledger --database evidence.sqlite3 verify-db
PYTHONPATH=src python -m labledger --database evidence.sqlite3 backup evidence-backup.sqlite3
```

单轮和多轮导入都通过 SQLite 事务写入；多轮中任意冲突会整体回滚。相同轮次标识再次出现时会拒绝覆盖，无论内容摘要相同还是不同。协议 1 使用 `reading` 表示测量值，协议 2 使用 `value`；两者归一到相同内部结构，但原始文件摘要保持不变。时间必须带时区，输入拒绝重复 JSON 键、重复测量标识、非有限数值和超出范围的读数。不同单位不会自动换算；同一组别跨仪器的数据会显示设备信息并提示人工核对校准。

质控先按校准偏移修正读数，再检查校准有效窗口、对照范围、单位、重复数与参考组。阻断性问题会让整轮退出分析，但仍保留原始读数、发现项和审计信息；组内变异和稳健异常值只作提示。报告提供分布摘要、重复性、参考组差值、设备与覆盖情况，不声称统计显著性。只有至少两轮可比较数据且没有待复核限制时，报告才标为可解释；该状态不是科学结论。

清单文件由 `bundles` 数组组成，每项包含相对文件 `path` 与该文件小写 SHA-256 `sha256`。路径不能为绝对路径、软链接或越出清单所在目录；所有摘要会在事务开始前校验。

JSON 证据包包含报告、审计事件、原始与校正读数以及包内容校验和；CSV 每行对应一条测量。`replay` 会用持久化的原值和校准上下文重跑质量规则，不覆盖已有记录。SQLite 备份通过数据库备份接口创建，并在替换目标文件前执行完整性检查。

## 验证

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src
PYTHONPATH=src python -m labledger.demo
```

项目仅使用 Python 标准库和 SQLite，无需安装第三方依赖或联网下载资源。
