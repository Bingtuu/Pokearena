-- 002_cards_regulation_mark_nullable: cards.regulation_mark 改为可空
-- task 005 CSM1DC 实测：基本能量 regulationMark=""（无赛制标记），统一存 NULL 而非空串。
-- SQLite 不支持改列约束，按官方表重建流程；其余列定义与 001_init 一致。

PRAGMA foreign_keys = OFF;

CREATE TABLE cards_new (
	card_id VARCHAR NOT NULL,
	set_id VARCHAR NOT NULL,
	number VARCHAR NOT NULL,
	number_display VARCHAR NOT NULL,
	name_full VARCHAR NOT NULL,
	species VARCHAR,
	owner VARCHAR,
	card_type VARCHAR NOT NULL,
	regulation_mark VARCHAR,
	rarity VARCHAR NOT NULL,
	stage VARCHAR,
	hp INTEGER,
	types JSON,
	evolves_from_text VARCHAR,
	evolves_from_id VARCHAR,
	evolution_chain_id VARCHAR,
	rule_box_type VARCHAR,
	has_rule_box BOOLEAN NOT NULL,
	is_tera BOOLEAN NOT NULL,
	union_position VARCHAR,
	prize_cards INTEGER NOT NULL,
	deck_limit INTEGER NOT NULL,
	is_ace_spec BOOLEAN NOT NULL,
	abilities JSON,
	attacks JSON,
	weakness JSON,
	resistance JSON,
	retreat_cost INTEGER,
	trainer_subtype VARCHAR,
	provides JSON,
	is_basic_energy BOOLEAN NOT NULL,
	text_raw TEXT NOT NULL,
	effect_tags JSON,
	name_en VARCHAR,
	name_ja VARCHAR,
	name_zh_tw VARCHAR,
	source VARCHAR NOT NULL,
	fetched_at DATETIME NOT NULL,
	status VARCHAR NOT NULL,
	PRIMARY KEY (card_id),
	FOREIGN KEY(set_id) REFERENCES sets (set_id),
	FOREIGN KEY(evolves_from_id) REFERENCES cards_new (card_id)
);

INSERT INTO cards_new SELECT * FROM cards;

DROP TABLE cards;

ALTER TABLE cards_new RENAME TO cards;

CREATE INDEX IF NOT EXISTS ix_cards_is_basic_energy ON cards (is_basic_energy);
CREATE INDEX IF NOT EXISTS ix_cards_is_tera ON cards (is_tera);
CREATE INDEX IF NOT EXISTS ix_cards_name_full ON cards (name_full);
CREATE INDEX IF NOT EXISTS ix_cards_regulation_mark ON cards (regulation_mark);
CREATE INDEX IF NOT EXISTS ix_cards_set_id ON cards (set_id);
CREATE INDEX IF NOT EXISTS ix_cards_species ON cards (species);
CREATE INDEX IF NOT EXISTS ix_cards_status ON cards (status);

PRAGMA foreign_keys = ON;
