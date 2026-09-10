from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Match, Swipe, SwipeAction

User = get_user_model()


class SwipeModelTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_same_pair_can_only_swipe_once(self):
        Swipe.objects.create(swiper=self.a, target=self.b, action=SwipeAction.LIKE)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Swipe.objects.create(swiper=self.a, target=self.b, action=SwipeAction.PASS)

    def test_reverse_direction_is_a_different_swipe(self):
        Swipe.objects.create(swiper=self.a, target=self.b, action=SwipeAction.LIKE)
        Swipe.objects.create(swiper=self.b, target=self.a, action=SwipeAction.LIKE)
        self.assertEqual(Swipe.objects.count(), 2)


class MatchModelTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_pair_kwargs_orders_by_id(self):
        self.assertEqual(Match.pair_kwargs(self.b, self.a), {"user_a": self.a, "user_b": self.b})
        self.assertEqual(Match.pair_kwargs(self.a, self.b), {"user_a": self.a, "user_b": self.b})

    def test_duplicate_pair_rejected(self):
        Match.objects.create(**Match.pair_kwargs(self.a, self.b))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Match.objects.create(**Match.pair_kwargs(self.b, self.a))

    def test_reversed_order_rejected_by_check_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Match.objects.create(user_a=self.b, user_b=self.a)

    def test_other_user(self):
        match = Match.objects.create(**Match.pair_kwargs(self.a, self.b))
        self.assertEqual(match.other_user(self.a), self.b)
        self.assertEqual(match.other_user(self.b), self.a)
