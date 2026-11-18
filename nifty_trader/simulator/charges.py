"""
Realistic Indian F&O (Options) Statutory Taxes, Regulatory Fees, and Brokerage Calculator.

Matches current standard discount broker fee structure (Zerodha / Dhan / AngelOne):
- Brokerage: Rs. 20 per executed order (Flat)
- STT (Securities Transaction Tax): 0.1% on Option Premium Sell Turnover
- Exchange Transaction Charges: 0.0505% on Premium Turnover (NSE)
- GST: 18% on (Brokerage + Exchange Transaction Charges + SEBI Fees)
- SEBI Charges: Rs. 10 per crore (0.0001% on Premium Turnover)
- Stamp Duty: 0.003% on Buy Value (Premium Turnover)
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class FOChargesBreakdown:
    buy_turnover: float
    sell_turnover: float
    total_turnover: float
    brokerage: float
    stt: float
    exchange_charges: float
    gst: float
    sebi_charges: float
    stamp_duty: float
    total_charges: float


class IndianFOChargesCalculator:
    """Calculates realistic transaction costs for Indian NIFTY options."""

    BROKERAGE_PER_ORDER: float = 20.0
    STT_SELL_RATE: float = 0.001          # 0.1% on sell premium
    EXCHANGE_TURNOVER_RATE: float = 0.000505 # 0.0505% on total premium turnover
    GST_RATE: float = 0.18               # 18% GST
    SEBI_RATE: float = 0.000001          # Rs 10 per crore
    STAMP_DUTY_BUY_RATE: float = 0.00003 # 0.003% on buy premium

    @classmethod
    def calculate(
        cls,
        buy_price: float,
        sell_price: float,
        qty: int,
    ) -> FOChargesBreakdown:
        """
        Calculates all statutory fees and brokerage for a completed round-trip option trade.
        """
        buy_turnover = round(buy_price * qty, 2)
        sell_turnover = round(sell_price * qty, 2)
        total_turnover = buy_turnover + sell_turnover

        # 1. Brokerage: Rs. 20 on Buy, Rs. 20 on Sell
        brokerage = cls.BROKERAGE_PER_ORDER * 2.0

        # 2. STT: on Sell turnover only
        stt = round(sell_turnover * cls.STT_SELL_RATE, 2)

        # 3. Exchange Turnover Charges: on total buy+sell premium turnover
        exchange_charges = round(total_turnover * cls.EXCHANGE_TURNOVER_RATE, 2)

        # 4. SEBI Charges
        sebi_charges = round(total_turnover * cls.SEBI_RATE, 2)

        # 5. Stamp Duty: on buy value only
        stamp_duty = round(buy_turnover * cls.STAMP_DUTY_BUY_RATE, 2)

        # 6. GST: 18% on (Brokerage + Exchange Charges + SEBI Charges)
        taxable_services = brokerage + exchange_charges + sebi_charges
        gst = round(taxable_services * cls.GST_RATE, 2)

        # Total Deductions
        total_charges = round(
            brokerage + stt + exchange_charges + sebi_charges + stamp_duty + gst, 2
        )

        return FOChargesBreakdown(
            buy_turnover=buy_turnover,
            sell_turnover=sell_turnover,
            total_turnover=total_turnover,
            brokerage=brokerage,
            stt=stt,
            exchange_charges=exchange_charges,
            gst=gst,
            sebi_charges=sebi_charges,
            stamp_duty=stamp_duty,
            total_charges=total_charges,
        )
