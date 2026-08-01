"""冒烟测试：建库 → 插入一个 set + 一张 card → 读回断言字段。"""

from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ptcgdb.migrations import apply_migrations
from ptcgdb.orm import Card, Set
from ptcgdb.schemas import Card as CardSchema


def test_smoke_insert_and_read_back(tmp_path):
    db_path = tmp_path / "test.db"
    apply_migrations(db_path)

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.add(
            Set(
                set_id="CSV1C",
                name_zh="亘古开来",
                era="朱&紫",
                release_date=date(2025, 1, 17),
                regulation_mark="G",
                expected_count=127,
                expected_secret_count=30,
                source="manual",
                fetched_at="2026-08-01T00:00:00",
            )
        )
        session.add(
            Card(
                card_id="CSV1C-009",
                set_id="CSV1C",
                number="009",
                number_display="009/127",
                name_full="新叶喵",
                species="新叶喵",
                owner=None,
                card_type="pokemon",
                regulation_mark="G",
                rarity="C",
                stage="基础",
                hp=70,
                types=["草"],
                evolves_from_text=None,
                evolves_from_id=None,
                evolution_chain_id=None,
                rule_box_type=None,
                has_rule_box=False,
                is_tera=False,
                union_position=None,
                prize_cards=1,
                deck_limit=4,
                is_ace_spec=False,
                abilities=None,
                attacks=[
                    {
                        "name": "抓",
                        "cost": [{"type": "草", "count": 1}],
                        "damage_base": 10,
                        "damage_modifier": None,
                        "effect_text": "",
                    }
                ],
                weakness={"type": "火", "value": "×2"},
                resistance=None,
                retreat_cost=1,
                trainer_subtype=None,
                provides=None,
                is_basic_energy=False,
                text_raw="",
                effect_tags=None,
                name_en=None,
                name_ja=None,
                name_zh_tw=None,
                source="manual",
                fetched_at=datetime(2026, 8, 1),
                status="active",
            )
        )
        session.commit()

        card = session.get(Card, "CSV1C-009")
        assert card is not None
        assert card.name_full == "新叶喵"
        assert card.set_id == "CSV1C"
        assert card.types == ["草"]
        assert card.attacks[0]["cost"] == [{"type": "草", "count": 1}]
        assert card.weakness == {"type": "火", "value": "×2"}
        assert card.prize_cards == 1
        assert card.deck_limit == 4
        assert card.is_basic_energy is False

        # ORM 行可直接喂给 SDK 返回模型（frozen Pydantic）
        parsed = CardSchema.model_validate(card, from_attributes=True)
        assert parsed.card_id == "CSV1C-009"
        assert parsed.attacks[0].damage_base == 10
