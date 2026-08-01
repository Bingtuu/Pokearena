-- 003_sets_release_date_nullable: sets.release_date 改为可空
-- task 005 实测：mik 对特典系列（SMP/SSP/SVP）无发售日（占位值 0001-01-01），
-- 垃圾日期按 NULL 落库比脏数据更忠实；cards.set_id 的外键在重建期间由 PRAGMA 关闭保护。

PRAGMA foreign_keys = OFF;

CREATE TABLE sets_new (
	set_id VARCHAR NOT NULL,
	name_zh VARCHAR NOT NULL,
	era VARCHAR NOT NULL,
	release_date DATE,
	regulation_mark VARCHAR NOT NULL,
	expected_count INTEGER,
	expected_secret_count INTEGER,
	source VARCHAR NOT NULL,
	fetched_at VARCHAR NOT NULL,
	PRIMARY KEY (set_id)
);

INSERT INTO sets_new SELECT * FROM sets;

DROP TABLE sets;

ALTER TABLE sets_new RENAME TO sets;

PRAGMA foreign_keys = ON;
