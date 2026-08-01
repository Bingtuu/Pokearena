-- 001_init: 建全部表与索引（由 ptcgdb.orm metadata 生成，勿手改）
-- PRD §7.1 ~ §7.3；IF NOT EXISTS 保证幂等


CREATE TABLE IF NOT EXISTS legality_snapshots (
	snapshot_id VARCHAR NOT NULL, 
	format VARCHAR NOT NULL, 
	effective_from DATE NOT NULL, 
	effective_to DATE, 
	allowed_marks JSON NOT NULL, 
	allowed_basic_energy_types JSON NOT NULL, 
	whitelist_cards JSON NOT NULL, 
	banned_cards JSON NOT NULL, 
	mark_overrides JSON NOT NULL, 
	latest_text_overrides JSON NOT NULL, 
	source_url VARCHAR, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (snapshot_id)
);

CREATE INDEX IF NOT EXISTS ix_legality_snapshots_format_effective_from ON legality_snapshots (format, effective_from);


CREATE TABLE IF NOT EXISTS meta (
	"key" VARCHAR NOT NULL, 
	value VARCHAR NOT NULL, 
	PRIMARY KEY ("key")
);


CREATE TABLE IF NOT EXISTS name_groups (
	group_key VARCHAR NOT NULL, 
	display_name VARCHAR NOT NULL, 
	rule_note VARCHAR, 
	PRIMARY KEY (group_key)
);


CREATE TABLE IF NOT EXISTS rules_documents (
	doc_id VARCHAR NOT NULL, 
	title VARCHAR NOT NULL, 
	version_label VARCHAR, 
	effective_from DATE, 
	source_url VARCHAR, 
	local_path VARCHAR, 
	note VARCHAR, 
	PRIMARY KEY (doc_id)
);


CREATE TABLE IF NOT EXISTS scrape_runs (
	run_id VARCHAR NOT NULL, 
	source VARCHAR NOT NULL, 
	started_at DATETIME NOT NULL, 
	finished_at DATETIME, 
	card_count INTEGER, 
	ok_count INTEGER, 
	question_count INTEGER, 
	missing_count INTEGER, 
	lists_path VARCHAR, 
	status VARCHAR NOT NULL, 
	manifest_hash VARCHAR, 
	PRIMARY KEY (run_id)
);


CREATE TABLE IF NOT EXISTS sets (
	set_id VARCHAR NOT NULL, 
	name_zh VARCHAR NOT NULL, 
	era VARCHAR NOT NULL, 
	release_date DATE NOT NULL, 
	regulation_mark VARCHAR NOT NULL, 
	expected_count INTEGER, 
	expected_secret_count INTEGER, 
	source VARCHAR NOT NULL, 
	fetched_at VARCHAR NOT NULL, 
	PRIMARY KEY (set_id)
);


CREATE TABLE IF NOT EXISTS cards (
	card_id VARCHAR NOT NULL, 
	set_id VARCHAR NOT NULL, 
	number VARCHAR NOT NULL, 
	number_display VARCHAR NOT NULL, 
	name_full VARCHAR NOT NULL, 
	species VARCHAR, 
	owner VARCHAR, 
	card_type VARCHAR NOT NULL, 
	regulation_mark VARCHAR NOT NULL, 
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
	FOREIGN KEY(evolves_from_id) REFERENCES cards (card_id)
);

CREATE INDEX IF NOT EXISTS ix_cards_is_basic_energy ON cards (is_basic_energy);
CREATE INDEX IF NOT EXISTS ix_cards_is_tera ON cards (is_tera);
CREATE INDEX IF NOT EXISTS ix_cards_name_full ON cards (name_full);
CREATE INDEX IF NOT EXISTS ix_cards_regulation_mark ON cards (regulation_mark);
CREATE INDEX IF NOT EXISTS ix_cards_set_id ON cards (set_id);
CREATE INDEX IF NOT EXISTS ix_cards_species ON cards (species);
CREATE INDEX IF NOT EXISTS ix_cards_status ON cards (status);


CREATE TABLE IF NOT EXISTS card_relations (
	card_id VARCHAR NOT NULL, 
	related_card_id VARCHAR NOT NULL, 
	relation_type VARCHAR NOT NULL, 
	confidence VARCHAR, 
	source VARCHAR, 
	PRIMARY KEY (card_id, related_card_id, relation_type), 
	FOREIGN KEY(card_id) REFERENCES cards (card_id), 
	FOREIGN KEY(related_card_id) REFERENCES cards (card_id)
);

CREATE INDEX IF NOT EXISTS ix_card_relations_related_card_id ON card_relations (related_card_id);


CREATE TABLE IF NOT EXISTS cards_name_group (
	card_id VARCHAR NOT NULL, 
	group_key VARCHAR NOT NULL, 
	PRIMARY KEY (card_id, group_key), 
	FOREIGN KEY(card_id) REFERENCES cards (card_id), 
	FOREIGN KEY(group_key) REFERENCES name_groups (group_key)
);


CREATE TABLE IF NOT EXISTS errata (
	errata_id VARCHAR NOT NULL, 
	card_id VARCHAR NOT NULL, 
	effective_from DATE NOT NULL, 
	corrected_text TEXT NOT NULL, 
	notice_url VARCHAR, 
	PRIMARY KEY (errata_id), 
	FOREIGN KEY(card_id) REFERENCES cards (card_id)
);


CREATE TABLE IF NOT EXISTS external_ids (
	card_id VARCHAR NOT NULL, 
	system VARCHAR NOT NULL, 
	external_id VARCHAR NOT NULL, 
	PRIMARY KEY (card_id, system), 
	FOREIGN KEY(card_id) REFERENCES cards (card_id)
);
