"""Tunable settings for the fuel subsidy validation engine.

Every threshold that can turn a line into a rejection lives here, so the
taskforce can adjust it without touching the logic.
"""
from dataclasses import dataclass, field


@dataclass
class Settings:
    # --- Quantity -----------------------------------------------------
    # Claimed litres may exceed EBM litres by this much before anything is cut
    # (absorbs rounding: 78.73 vs 78.7). Above it, only the excess is rejected.
    qty_abs_tolerance_l: float = 0.05
    qty_rel_tolerance: float = 0.001          # 0.1 %

    # --- Prices ---------------------------------------------------------
    # A unit price is "under-priced" only if it is below the RURA pump price
    # by more than this many RWF per litre.
    price_tolerance_rwf: float = 1.0
    # Plausible pump price range, used to repair numbers such as "2.927"
    # (thousands written with a dot) into 2927.
    min_plausible_price: float = 500.0
    max_plausible_price: float = 10_000.0

    # --- Arithmetic checks inside the claim (warnings, never rejections) --
    amount_tolerance_rwf: float = 2.0
    amount_rel_tolerance: float = 0.005

    # --- Subsidy ----------------------------------------------------------
    # Official subsidy rate per litre (RWF). None = trust the rate in the claim
    # file but flag lines whose rate differs from the claim's most common rate.
    official_subsidy_rate: float | None = None
    # Official rate per product (set by the administrator), e.g. {"DIESEL": 438, "PETROL": 438}.
    # When given, the subsidy is paid at this rate and a different claimed rate is noted.
    official_subsidy_rates: dict | None = None

    # --- Tax type ---------------------------------------------------------
    # EBM tax type codes treated as exempt (rejected). Confirm with RRA:
    # A = exempt, B = 18 %, C = zero-rated, D = non-VAT in EBM 2.0.
    exempt_tax_types: set = field(default_factory=lambda: {"A"})

    # --- Dates -------------------------------------------------------------
    # "Closed at" vs EBM SdcDateTime: gaps above this go to human review
    # (not rejection) — pump clocks and EBM clocks often differ.
    max_time_gap_hours: float = 24.0

    # --- Fallback matching when the slip number is unusable -----------------
    # Match on seller TIN + product + quantity + amount within this window.
    fallback_window_minutes: float = 30.0

    # --- Anomalies (always human review, never automatic rejection) ---------
    max_litres_per_vehicle_day: float = 400.0
    iqr_multiplier: float = 3.0              # statistical outlier fence
    min_refill_interval_minutes: float = 60.0
    # --- Buyer of the fuel (EBM ClientsTIN) ---------------------------------
    # Subsidised fuel is sold to transport operators: invoices without a buyer TIN,
    # or to a TIN different from the one usually used by that client, go to review.
    check_buyer_tin: bool = True
    anonymous_buyer_tins: tuple = ("999999999", "000000000", "0")

    # Card shared by many vehicles. Off by default: suppliers mask card numbers
    # (19xxxxxxxxxx3686) and fleets share cards, so this floods review.
    max_plates_per_card: int | None = None


DEFAULT = Settings()
