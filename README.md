# 校园快递代取平台 · 接口与数据测试

![campus-express-api-ci](https://github.com/zhongjiawei-dev/campus-express-test/actions/workflows/ci.yml/badge.svg)

这是我在校期间做的一个测试练习项目：自己写了一个校园快递代取的服务端，然后把下单、接单、配送、签收、评价这条链路从头测了一遍。仓库里既能跑服务，也能直接跑测试。

服务端没有用现成框架，HTTP 用 Python 标准库，数据放在 MariaDB。写它不是为了做个产品，而是为了让测试有真实的接口、真实的状态流转、真实的多表数据可以核对。

## 我做了什么

- 按「下单 → 接单 → 取件 → 送达 → 签收 → 评价」拆测试点，写了 113 条 pytest 用例，覆盖正常流程和各种不走运的情况
- 用 Postman 把 22 个接口过了一遍，重点看 Token 失效、越权查别人订单、参数边界
- 用 PyMySQL 直接查库，核对订单、钱包、流水、信用分四张表的数据能不能对上
- 每个订单节点都会写一条哈希存证，我改了订单状态、标题、金额去试，看存证能不能发现
- 发现 5 个服务端没处理好的地方，都写在 `docs/03-缺陷清单.md` 里，目前还没改

## 技术栈

Python 3.11+、pytest、requests、PyYAML、PyMySQL、MariaDB 10.6、Postman、GitHub Actions

## 目录

```
app/server.py              被测服务，22 个接口
tests/conftest.py          起服务、清库、登录、造订单的 fixture
tests/test_auth.py         注册登录、Token、资料脱敏
tests/test_order_create.py 下单参数、列表、详情、取消
tests/test_lifecycle.py    接单、取件、送达、签收、评价、钱包
tests/test_timeout.py      超时未接单
tests/test_chain.py        存证时间线与哈希校验
tests/test_db.py           多表数据核对
tests/test_data_driven.py  YAML 数据驱动
data/order_cases.yaml      下单参数用例数据
postman/                   Postman 集合，27 个请求
docs/                      测试计划、用例设计、缺陷清单、执行报告
```

## 本地跑起来

先准备数据库。我本机用的是 MariaDB 10.6：

```sql
CREATE DATABASE campus_test DEFAULT CHARSET utf8mb4;
CREATE USER 'campus'@'127.0.0.1' IDENTIFIED BY 'Campus@123';
GRANT ALL PRIVILEGES ON campus_test.* TO 'campus'@'127.0.0.1';
FLUSH PRIVILEGES;
```

装依赖、起服务：

```bash
pip install -r requirements.txt
python app/server.py --port 9300 --reset
```

`--reset` 会重建表并写入种子账号。另开一个终端跑测试：

```bash
pytest
```

测试会自己在空闲端口起一个服务，不需要提前开 9300。数据库连接可以用环境变量改：`DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD`、`DB_NAME`。

## 种子账号

| 角色 | 手机号 | 密码 | 初始钱包 |
| --- | --- | --- | --- |
| 管理员 | 13800000000 | Admin@123 | 0 |
| 学生（下单） | 13800000001 | Stu@123 | 300.00 |
| 骑手 A | 13800000002 | Run@123 | 50.00 |
| 骑手 B | 13800000003 | Run@456 | 50.00 |

## 实测结果

最近一次全量执行：

```
108 passed, 5 xfailed in 21.31s
```

5 条 xfailed 不是写错用例，是我故意留着没改的服务端问题。每一条都写了 `reason`，指向 `docs/03-缺陷清单.md` 里对应的编号。这些问题在当前版本仍然能复现，我没有为了让报告变绿去改断言。

Postman 集合在 `postman/campus-express.postman_collection.json`，导入后先跑「01 账号与鉴权」拿三个角色的 token，再跑后面的文件夹。集合里的 `order_id`、`cancel_id` 会自动串起来。

## 已知问题

见 [docs/03-缺陷清单.md](docs/03-缺陷清单.md)。简单说：签收后信用分不加、重复签收会重复扣钱、超时订单还能接、存证哈希没算金额、同一单能重复评价。

## 一点说明

服务端是练习用的，业务规则按校园代取场景简化过，比如没有真实支付、没有消息推送。测试里对金额、状态、权限的断言都是按我自己定的接口约定写的，接口清单位于 `docs/05-接口清单.md`。

GitHub Actions 会在每次 push 时起一个 MariaDB 容器，装依赖、跑全量用例，测试报告留在 artifact 里。
