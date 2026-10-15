# PaperWeave 入口。
#
#   make setup       委派给仓库根：建共享 .venv 并装 git 过滤器
#   make neo4j-up    启动 infra/neo4j-e09（bolt 7687，浏览器 7474；先停 neo4j-e08）
#   make neo4j-down  停止 neo4j-e09（数据保留在 infra/neo4j-e09/data/）
#   make check       环境自检：材料与入库文档目录、连库、版本与 edition、确认不是 v1 库
#   make embed       建向量索引并补算向量（Resolve 的语义阶段用）；需要 embedding 服务，只补算文本变过的对象
#   make test        写入管线与算子的检验（tests/；算子只在设置 GRAPH_VC_TEST_NEO4J_URI 时于测试实例上运行）
#   make lab         在本目录启动 JupyterLab
#   make workspace DIR=~/e09-runs/<名称>  在仓库外生成实验目录（.pi/mcp.json），在其中运行默认的 pi
#
# 写入路径已改用 packages/graph-vc 与 packages/graph-doc：python -m paperweave（见 README）；重建目标待 graph-doc 数据就绪后加入。
# 旧写入路径（表单编译与 Commit）见 tag e09-legacy-write：现有 neo4j-e09 库与 I3 实验由它建出。
#
# 当前用户若不在 docker 组：make neo4j-up DOCKER="sudo docker"

UV ?= uv
DOCKER ?= docker
RUN = $(UV) run
COMPOSE = $(DOCKER) compose -f ../infra/neo4j-e09/docker-compose.yml

.PHONY: setup neo4j-up neo4j-down check embed test lab workspace clean

setup:
	$(MAKE) -C .. setup

neo4j-up:
	$(COMPOSE) up -d

neo4j-down:
	$(COMPOSE) down

check:
	$(RUN) python -m paperweave.env_check

embed:
	$(RUN) python -m paperweave.store.embedding

test:
	$(RUN) pytest tests -q

lab:
	mkdir -p notebooks && $(RUN) jupyter lab --notebook-dir=notebooks

workspace:
	@test -n "$(DIR)" || (echo 'usage: make workspace DIR=~/e09-runs/<name> [ARGS=--enable-commit]' && exit 1)
	$(RUN) python -m paperweave.workspace $(DIR) $(ARGS)

clean:
	rm -rf notebooks/_scratch
