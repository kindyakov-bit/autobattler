"""Тесты для game/core/shop.py — классы Shop, ShopError и Player."""

import pytest
from game.core.shop import Shop, ShopError
from game.core.player import Player
from game.core.pool import Pool


# ---------- сценарий 1: три покупки → merge в ★2 ----------

class TestMergeThreeUnits:
    """Покупка трёх одинаковых юнитов сливается в ★2."""

    def test_three_buys_merge(self):
        pool = Pool({"warrior": 1})          # 30 копий, cost=1
        player = Player(gold=3)              # ровно на три покупки
        shop = Shop(pool)

        r1 = shop.buy(player, "warrior", cost=1)
        r2 = shop.buy(player, "warrior", cost=1)
        r3 = shop.buy(player, "warrior", cost=1)

        # все три вызова вернули "warrior" (до merge)
        assert r1 == "warrior"
        assert r2 == "warrior"
        assert r3 == "warrior★2"

        # золото списано полностью
        assert player.gold == 0

        # в резерве ровно один ★2-юнит
        assert player.reserve == ["warrior★2"]

        # пул: 30 − 3 (три take) + 2 (вернули при merge) = 29
        assert pool.available("warrior") == 29


# ---------- сценарий 2: недостаточно золота ----------

class TestNotEnoughGold:
    """buy при gold < cost бросает ShopError."""

    def test_buy_insufficient_gold(self):
        pool = Pool({"warrior": 1})
        player = Player(gold=0)
        shop = Shop(pool)

        with pytest.raises(ShopError, match=r"нужно 1 золота, есть 0"):
            shop.buy(player, "warrior", cost=1)


# ---------- сценарий 3: юнит кончился в пуле ----------

class TestPoolExhausted:
    """Когда все копии ушли — buy бросает ShopError."""

    def test_pool_exhausted(self):
        pool = Pool({"warrior": 1})         # ровно 30 копий
        player = Player(gold=100)           # золота хватит на всё
        player.max_board = 100              # достаточно для теста, чтобы перекладывать на доску
        shop = Shop(pool)

        # Каждые 3 покупки сливаются в ★2 и возвращают 2 копии в пул.
        # После каждого цикла из 3-х покупок пул теряет ровно 1 копию.
        # После 28 циклов (84 покупка) pool=2, затем ещё 2 take → pool=0.
        # Итого: 86 покупки исчерпывают все копии.
        for _ in range(86):
            shop.buy(player, "warrior", cost=1)
            # Перекладываем на доску, чтобы резерв не переполнился (max_bench=20)
            if player.reserve and len(player.board) < player.max_board:
                shop.place(player, 0)

        assert pool.available("warrior") == 0

        # следующая покупка — ошибка
        with pytest.raises(ShopError, match=r"warrior: копий в пуле не осталось"):
            shop.buy(player, "warrior", cost=1)


# ---------- сценарий 4: ★3 merge (три ★2 → одна ★3) ----------

class TestStar3Merge:
    """Три ★2-юнита сливаются в один ★3."""

    def test_three_star2_merge_to_star3(self):
        """Создаём три ★2 юнита и сливаем их в ★3."""
        pool = Pool({"warrior": 1})
        player = Player(gold=9)  # 9 золотых: 3×3 для трёх ★2
        shop = Shop(pool)

        # Создаём первый ★2 (три покупки)
        r1 = shop.buy(player, "warrior", cost=1)
        r2 = shop.buy(player, "warrior", cost=1)
        r3 = shop.buy(player, "warrior", cost=1)
        assert r3 == "warrior★2"
        assert player.reserve == ["warrior★2"]

        # Создаём второй ★2 (ещё три покупки)
        r4 = shop.buy(player, "warrior", cost=1)
        r5 = shop.buy(player, "warrior", cost=1)
        r6 = shop.buy(player, "warrior", cost=1)
        assert player.reserve == ["warrior★2", "warrior★2"]

        # Создаём третий ★2 (ещё три покупки) → слияние 3★2→★3
        r7 = shop.buy(player, "warrior", cost=1)
        r8 = shop.buy(player, "warrior", cost=1)
        r9 = shop.buy(player, "warrior", cost=1)
        assert r9 == "warrior★3"

        # В резерве ровно один ★3-юнит
        assert player.reserve == ["warrior★3"]
        assert pool.available("warrior") == 27  # 30 - 9 (девять take ★1) + 6 (три merge refund по 2) = 27 ★1

    def test_star3_reserves_three_star2(self):
        """Создаём три ★2 мага и сливаем их в ★3."""
        pool = Pool({"mage_acolyte": 1})
        player = Player(gold=9)
        shop = Shop(pool)

        # Создаём первый ★2 мага (три покупки)
        for _ in range(3):
            shop.buy(player, "mage_acolyte", cost=1)
        assert "mage_acolyte★2" in player.reserve

        # Создаём второй ★2 мага (ещё три покупки)
        for _ in range(3):
            shop.buy(player, "mage_acolyte", cost=1)
        assert sum(1 for r in player.reserve if "mage_acolyte★2" in r) == 2

        # Создаём третий ★2 мага (ещё три покупки) → слияние 3★2→★3
        for _ in range(3):
            shop.buy(player, "mage_acolyte", cost=1)

        assert "mage_acolyte★3" in player.reserve


# ---------- сценарий 5: цепочка merge (6 базовых → 2 ★2 → 1 ★3) ----------

class TestChainMerge:
    """Цепочка: 9 копий = 3×(3→★2), затем 3★2→★3."""

    def test_nine_base_to_star3(self):
        """9 базовых юнитов → один ★3."""
        pool = Pool({"archer_scout": 1})
        player = Player(gold=9)
        shop = Shop(pool)

        # Покупка 9 копий archer_scout (cost=1 каждая)
        for i in range(9):
            result = shop.buy(player, "archer_scout", cost=1)

        # Должен остаться только ★3
        assert player.reserve == ["archer_scout★3"]


# ---------- сценарий 6: смешанный ростер (разные юниты) ----------

class TestMixedRosterMerges:
    """Микс разных юнитов и merge внутри каждого класса."""

    def test_different_units_no_cross_merge(self):
        """Разные юниты НЕ сливаются друг с другом."""
        pool = Pool({"warrior_freshman": 1, "mage_acolyte": 1})
        player = Player(gold=6)
        shop = Shop(pool)

        # Покупаем двух разных юнитов
        shop.buy(player, "warrior_freshman", cost=1)
        shop.buy(player, "mage_acolyte", cost=1)

        # Они должны лежать отдельно в reserve (без merge)
        assert len(player.reserve) == 2
        assert "warrior_freshman" in player.reserve
        assert "mage_acolyte" in player.reserve

    def test_mix_merge_and_separate(self):
        """3 одинаковых → ★2, ещё 1 отдельный = 2 элемента в reserve."""
        pool = Pool({"warrior": 1})
        player = Player(gold=4)
        shop = Shop(pool)

        # Три "warrior" → ★2
        for _ in range(3):
            shop.buy(player, "warrior", cost=1)
        
        # Один ещё "warrior" → отдельный (не сливается с ★2)
        r4 = shop.buy(player, "warrior", cost=1)
        
        assert r4 == "warrior"  # не слит, т.к. нужно 3 одинаковых для ★2
        assert "warrior★2" in player.reserve
        assert "warrior" in player.reserve
        assert len(player.reserve) == 2


# ---------- сценарий 7: sell возвращает в пул ----------

class TestSellRefund:
    """Продажа юнита возвращает копию в пул."""

    def test_sell_returns_to_pool(self):
        pool = Pool({"warrior": 1})
        player = Player(gold=3)
        shop = Shop(pool)

        # Создаём ★2
        for _ in range(3):
            shop.buy(player, "warrior", cost=1)

        assert pool.available("warrior") == 29  # после merge: 30-3+2=29

        # Продаём ★2 из reserve
        base = shop.sell(player, 0)
        assert base == "warrior"
        assert player.reserve == []

        # Пул должен увеличиться на 1 (вернули копию)
        assert pool.available("warrior") == 30


# ---------- сценарий 8: place и remove ----------

class TestPlaceRemove:
    """Размещение юнита на доску и удаление обратно."""

    def test_place_then_remove(self):
        pool = Pool({"warrior": 1})
        player = Player(gold=1)
        shop = Shop(pool)

        # Покупаем и размещаем
        shop.buy(player, "warrior", cost=1)
        unit = shop.place(player, 0)

        assert unit["name"] == "warrior"
        assert unit["star"] == 1
        assert len(player.board) == 1
        assert len(player.reserve) == 0

        # Удаляем обратно
        removed = shop.remove_from_board(player, 0)
        assert removed == "warrior"
        assert len(player.board) == 0
        assert len(player.reserve) == 1

    def test_place_star2(self):
        """Размещение ★2-юнита."""
        pool = Pool({"warrior": 1})
        player = Player(gold=3)
        shop = Shop(pool)

        # Создаём ★2
        for _ in range(3):
            shop.buy(player, "warrior", cost=1)

        unit = shop.place(player, 0)
        assert unit["name"] == "warrior★2"
        assert unit["star"] == 2


# ---------- сценарий 9: roll ----------

class TestRoll:
    """Ролл магазина возвращает случайные юниты."""

    def test_roll_returns_items(self):
        pool = Pool({"warrior": 1, "mage": 1})
        unit_costs = {"warrior": 1, "mage": 1}
        shop = Shop(pool, unit_costs=unit_costs)

        items = shop.roll(count=5)
        assert len(items) == 5
        for item in items:
            assert "name" in item
            assert "cost" in item


# ---------- сценарий 10: get_available_units ----------

class TestGetAvailableUnits:
    """Список доступных юнитов в пуле."""

    def test_available_units_reflects_pool(self):
        pool = Pool({"warrior": 1, "mage": 1})
        shop = Shop(pool)

        available = shop.get_available_units()
        assert set(available) == {"warrior", "mage"}

        # Покупаем всех
        player = Player(gold=2)
        shop.buy(player, "warrior", cost=1)
        shop.buy(player, "mage", cost=1)

        available = shop.get_available_units()
        assert set(available) == {"warrior", "mage"}  # Pool все ещё содержит (остались копии)


# ---------- сценарий 11: ★3 merge edge cases ----------

class TestStar3EdgeCases:
    """Граничные случаи для ★3."""

    def test_star3_from_exact_three_star2(self):
        """Ровно три ★2 → один ★3, без остатка."""
        pool = Pool({"warrior": 1})
        player = Player(gold=9)
        shop = Shop(pool)

        # Создаём три ★2
        for _ in range(3):
            for _ in range(3):
                shop.buy(player, "warrior", cost=1)

        assert player.reserve == ["warrior★3"]
        # Нет лишних ★2
        assert sum(1 for r in player.reserve if "★2" in r) == 0

    def test_four_star2_gives_one_star3_plus_one_star2(self):
        """Создаём 4★2 (12 базовых), проверяем итог.
        
        С немедленным merge: каждые 3★2 сливаются в ★3,
        поэтому после 12 покупок получаем 1★3 + 1★2.
        """
        pool = Pool({"warrior": 1})
        player = Player(gold=12)
        shop = Shop(pool)

        # Создаём четыре ★2 (каждый из 3-х базовых)
        for _ in range(4):
            for _ in range(3):
                shop.buy(player, "warrior", cost=1)

        # 4★2 → 3★2 сливаются в ★3, остаётся 1★2
        star3_count = sum(1 for r in player.reserve if "★3" in r)
        star2_count = sum(1 for r in player.reserve if "★2" in r)
        assert star3_count == 1, f"ожидался 1★3, получено {star3_count}"
        assert star2_count == 1, f"ожидался 1★2, получено {star2_count}"

    def test_mixed_star_levels_no_cross_merge(self):
        """★1 и ★2 одного юнита НЕ сливаются в ★3 (нужны два ★2)."""
        pool = Pool({"warrior": 1})
        player = Player(gold=4)
        shop = Shop(pool)

        # Создаём один ★2 и один ★1
        for _ in range(3):
            shop.buy(player, "warrior", cost=1)
        shop.buy(player, "warrior", cost=1)

        # В reserve: ★2 + ★1 (не должно быть ★3)
        assert "warrior★2" in player.reserve
        assert "warrior" in player.reserve
        assert not any("★3" in r for r in player.reserve)
