from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from app_config import DB_CHARSET, DB_HOST, DB_PASS, DB_PORT, DB_USER


# 不指定默认 database，使同一个连接可查询多个 schema（如 cs2_playtime/cs2_serverlist）
DB_DSN = URL.create(
    "mysql+pymysql",
    username=DB_USER,
    password=DB_PASS,
    host=DB_HOST,
    port=DB_PORT,
    database=None,
    query={"charset": DB_CHARSET},
)

# pool_pre_ping=True: 连接复用前先探活，降低 MySQL 空闲断连导致的报错
# pool_recycle=300: 降低长连接被中间网络设备回收后的使用失败概率
engine = create_engine(DB_DSN, pool_pre_ping=True, pool_recycle=300)
