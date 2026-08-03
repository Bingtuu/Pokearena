-- 007：A2 卡面比对三件技术债修复（PRD v1.11，task 030）
-- F-01：sets.card_face_total = 卡面分母种子（商品主列表收录数；NULL=未覆盖不猜）
-- F-02：cards.alias_of = mik 双重列示别名指向正本 card_id（NULL=正本/普通卡）
-- F-03：无 schema 变更（is_tera 既有列，derive 改走 mapping 层 ptcd subtypes 富化）

ALTER TABLE sets ADD COLUMN card_face_total INTEGER;

ALTER TABLE cards ADD COLUMN alias_of VARCHAR REFERENCES cards(card_id);
