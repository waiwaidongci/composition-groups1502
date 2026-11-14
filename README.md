# 砺穗生物炭组成比较册

对五个互斥分析相的相对量做闭合、显式乘法零替换和CLR，在Aitchison几何里比较预定义工艺组，并把全局证据交给独立补样。

砺穗生物炭实验室有15位化学分析员，上游 `lisui-biochar-phase-202611.csv` 包含炭质相、硅酸盐相、碳酸盐相、磷酸盐相及其余相。过去在表格里直接相关百分比、遇到零静默加常数、看到组差就归因工艺，导致闭合约束伪相关、替换假设不可追溯、解释忽略离散度。本系统替代组成变换、全局置换与复配补样归档环节，下游由材料负责人批准独立补样，阅读者下载获批CSV。当前全部是独立合成样本，不是实测成分、产量或工艺原因证明。

## 启动

```sh
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```

含中文与空格的目录可启动。前端 http://localhost:18233 ，API文档 http://localhost:19233/docs ，MySQL localhost:17733。恰好frontend/backend/worker/db/redis五服务，均有健康检查；backend/worker等待数据库与Redis，frontend等待backend。Nginx `/api/` 去前缀代理。命名卷分别持久化MySQL、Redis任务队列、backend/worker共享完整结果JSON。

| 角色 | 账号 | 密码 | 典型动作 |
|---|---|---|---|
| admin 材料负责人 | admin@lisui.demo | Lisui2026! | 六页；创建研究、批注、提交、批准/退回补样 |
| analyst 组成研究员 | analyst@lisui.demo | Lisui2026! | 六页；来源核对、配置δ/B、提交运行和补样说明 |
| viewer 补样阅读者 | viewer@lisui.demo | Lisui2026! | 六页只读；下载获批完成研究CSV |

受理即持久：`POST /runs` 先提交数据库行再入队。队列暂不可用时任务仍保留为 `queued`，后端内嵌恢复执行器和worker的定期扫描会把缺失的队列项补回。

JWT角色在后端执行，viewer写入403、analyst审批403、未获批导出403、重复审批409。登录/批注/排队/worker完成/建议与审批留审计。登录IP每分钟最多30次，另有统一错误中间件。请求校验422只返回loc/msg文本，不回显含NaN/Inf的input。部署时修改JWT_SECRET及Compose内MySQL口令。

## 一天的研究剧本

1. 09:00 顾砚登录，核对 `LS-01` 正组成研究：工艺A/B/C各24个独立样本，五个互斥相通道，原相对量并非都合计100。
2. 09:05 打开 `LS-02`，12行含零，其中每组首样本有两个零。零按未检出通道记录，不静默加伪计数。
3. 09:10 查看 `LS-03` 恒定组成边界，SST=0、PERMANOVA未定义，系统拒绝运行。
4. 09:15 为LS-02冻结δ=.001、B199、seed2026，创建“三工艺组成复核”；系统保留原量、闭合份额、替换后份额和CLR。
5. 09:16 独立worker固定各组规模置换标签，保存199个null R²，以R²上尾含并列+1求全局p。
6. 09:20 真实HTTP运行的LS-02得到R²约.02814246、pseudo-F约.99903、p=.435。这份数据未给出强组差证据，仍可为未检出限与δ假设做独立补样。
7. 09:25 写三工艺同规模补样说明，注明仅报告组内距离描述、未正式检验离散度同质、不将组差当工艺原因。
8. 10:00 罗岑批准归档，程禾以阅读者下载 `composition-run-N.csv`，供独立复配补样核对。

## 六页与五实体

组成总览、相份额来源、替换与置换、组间证据、复配补样、研究留痕。`CompositionStudy / ComponentSpec / CompositionSample / CompositionRun / ResampleNote` 均贯穿表、model、schema、service、route、前端API、store与页面/组件，另有User/Audit。来源数值/成分/组标签只读核对，样本批注可写；运行创建时冻结完整快照，后续批注不改历史结果。

seed为3研究×3工艺×24样本=216行、15个成分定义。LS-01正组成，LS-02含12行零分量（每组4行），LS-03固定[50,20,15,10,5]恒定边界。固定种子290/291/292生成，五相互斥，其余相为剩余通道，仅解释相对组成。自然键email、study code、(study,sample code)、(study,component code/position)、基线run name；seed只补缺失，不覆盖用户批注/已批准建议。`SEED_DEMO=true`启动执行一次，失败记日志，也可独立重复执行。

MySQL连续标量 `default_delta`、`delta` 明确 `DOUBLE(asdecimal=False)`，数值向量/SS/null通过JSON保存Python双精度，未用单精度Float列。

## 组成几何

原相对量x非负且非全零，先按行闭合为q=x/Σx。实现先除行最大值防止求和溢出；若正值闭合后下溢到0，受控失败。设一行有z个原始零：

```text
零位置：r_j = δ
正位置：r_j = q_j * (1 − zδ)
要求0 < δ < 1/z
没有零：r = q，仅闭合
CLR_j = log(r_j) − mean(log(r))
Aitchison距离 = ||CLR(x) − CLR(y)||₂
```

δ以闭合后比例为单位，不是原量加数，也不自动估计检出限。保留raw/closed/replaced/CLR及零数，零替换可能改变结论。API允许(0,1)并逐行严格检查zδ<1；UI最小步长.0001。每研究固定4–6个不同成分，本题5个；每组至少2个独立样本，2–5组，最多300样本且N×B≤150000。

组CLR均值、原替换份额算术均值、closure(exp(组CLR均值))的Aitchison中心分别保存，界面条带使用后者，不把它当原份额算术均值。

## PERMANOVA与数值边界

在CLR欧氏空间，T=Σ||Z_i−总均值||²，W=Σ组Σ||Z_i−组均值||²，B=T−W，R²=B/T，pseudo-F=(B/(k−1))/(W/(N−k))。总中心相对首行锚定，再按最大中心差缩放计算SS比例，避免用绝对方差阈值误拒可分辨小变化；组内SS与各组汇总使用math.fsum，标签改名不应改变统计量。

- T=0时未定义，拒绝；不把常量组成说成“无差异p=1”。
- W=0且T>0时R²=1、F无界，JSON以F=null/F_status=unbounded表示；置换仍保存有限R²，检验继续。
- F超数值范围时另标numerical_overflow，不伪造有限值或写JSON Infinity。

B199–999次均匀置换标签，组规模保持，固定seed与自然键排序复现。固定N/k自由度下R²与F单调等价，因此null只保存R²，包含完美分离情况。p=(1+#null R²≥观测R²)/(B+1)。当前v2以 `64*eps*max(1,|观测R²|,max|null R²|)` 作声明的机器尺度并列保护，避免数学同一划分被浮点分组汇总顺序漏计；该保护只用于R²比较，不用于SST拒绝。

全局组差也可受组内离散度影响，只给到组CLR质心的平均/最大距离描述，未正式检验离散度同质；独立与零假设下标签可交换是前提。不是工艺因果、性能概率、逐组对照p或事后选择保证。p最小分辨率1/(B+1)，有Monte Carlo波动。

当前算法/指纹版本为 `closure-replacement-clr-permanova-v2`；恢复不改变版本或指纹。v1在真实6点夹具的数学并列漏计曾被独立复核发现；v2修复、空卷重跑及原证据详见TESTING，不用历史v1运行冒充最终结果。

## 中断与自动恢复

任务在被受理后可能遇到三类中断，系统按“数据库是受理凭据、结果文件是完成凭据、租约是所有权凭据”处理：

1. **队列断连**：已受理行仍是 `queued`，恢复扫描发现Redis列表缺失该id时自动重新入队；重复入队无副作用。页面恢复状态 `queue_pending`，原因写入 `recovery_reason`。
2. **计算进程失联**：接手通过带条件的原子更新取得租约，`attempts` 与 `lease_token` 同时匹配才成功，多进程并发只有一个赢家。计算期间后台线程续租；若续租失败（已被接手），旧进程丢弃自己的结果，绝不回传覆盖。
3. **结果写出后、完成状态保存前中断**：结果先以临时文件+`fsync`+原子改名发布到 `/artifacts/run-<id>-attempt-<n>.json`，再置 `saving`，最后置 `completed`。恢复扫描或下一任接手会核对文件中的运行id、attempt、算法版本、冻结输入指纹、结果指纹与配置（δ/B/seed），匹配才采纳原文件，不重算、不换种子。

租约默认30秒（`WORKER_LEASE_SECONDS`），计算期间后台每10秒续租，心跳5秒，扫描2秒；连续接手达到 `WORKER_MAX_ATTEMPTS`（默认8）时置 `failed` 并把原因写进 `error`，页面显示失败原因。恢复沿用受理时冻结的 `input_snapshot`、δ、置换次数与seed；同seed在恢复下必然得到同一结果。

`refresh` 后 `GET /runs` 返回 `recovery_state`（`normal/queue_pending/recovering/saving/recovered/failed`）、`attempts`、`recovery_count`、`recovery_reason`、`result_hash`、`artifact_key`、`finished_at`。租约token不返回给客户端。审批时把当前完成结果的 `approved_result_hash` 固定到运行行，导出独立重验结果文件与该指纹，二者不一致返回409；旧档案（升级前无结果文件/指纹）直接用数据库结果，保持可读可导出。

可并发执行：`docker compose up -d --scale worker=3`（worker不再固定container_name，心跳按实例共享，健康检查只要有一个实例在跑即通过）。兜底由 `INLINE_RUNNER_ENABLED`（默认true）控制后端内嵌执行器，它只在worker心跳超过15秒未更新时工作，并与worker走同一套 claim/lease/发布协议；队列不可用时 `/health` 返回 `degraded` 而非拖垮API。

## 工程与开发

Vue3.5/Pinia3/VueRouter4/TypeScript5.7/Vite6.4.6；Python3.11/FastAPI0.115/SQLAlchemy2/NumPy2.2/SciPy1.15/PyMySQL1.1；MySQL8/Redis7/Nginx1.27。后端真算所有变换、SS、R²与置换，前端只展示真实结果。

```sh
# backend，先准备MySQL/Redis，设置DATABASE_URL、REDIS_URL
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8000
# 另开终端在backend启动worker；本地需可写/artifacts，建议Compose
python -m src.worker
# 前端从项目根进入frontend，Vite代理/api到localhost:8000
cd ../frontend
npm ci
npm run dev
```

`backend/src/{routes,controllers,services,models,schemas,middlewares,utils,constants,config}` 按来源、变换、PERMANOVA、运行、审阅和横切拆分；恢复逻辑集中在`services/recovery_service.py`，单次执行协议在`services/runner_service.py`，后端内嵌执行器在`services/inline_runner.py`；`backend/scripts/seed_demo.py`；migration为可选索引，metadata首次建表，恢复列由`ensure_schema()`就地补齐，非独立全量DDL。`frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}` 为Vue应用。

RunSummary跨首页/结果/审阅，GroupProfiles跨首页/结果，CompositionMatrix跨来源/结果，另有StudySelector、PermutationPlot及通用DataTable/Notice/StatusBadge。两hooks useResearch/useAction及utils处理公共状态。角色枚举backend/constants/roles与frontend/constants/enums参与鉴权/角色显示，队列状态backend/constants/status与前端RunStatus参与worker/StatusBadge，审阅Literal在backend/schemas/note和model/service/前端ReviewStatus。

.env含COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、JWT_SECRET、SEED_DEMO，DATABASE_URL/REDIS_URL由Compose定义；恢复相关`WORKER_LEASE_SECONDS`、`WORKER_SWEEP_SECONDS`、`WORKER_MAX_ATTEMPTS`、`INLINE_RUNNER_ENABLED`、`ARTIFACT_DIR`有默认值。源码不含测试截图/日志；关键JSON/CSV、截图与已知差异在同批test-artifacts/gb-0029。多worker并发与崩溃/断连恢复已支持；无来源上传、无真实设备操作。清理仅本题：`docker compose down -v --remove-orphans`。MIT License。
