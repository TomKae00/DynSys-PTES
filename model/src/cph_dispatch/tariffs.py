"""Transparent discharge-credit candidates; conditional signals are not contract prices."""

import numpy as np
import pandas as pd


def _monthly_mean(series):
    months = series.index.tz_convert("Europe/Copenhagen").strftime("%Y-%m")
    return series.groupby(months).transform("mean")


def _bounded_mean_credit(signal, *, level, scale, lower, upper):
    """Match each sampled Danish month's arithmetic credit mean after clipping.

    The hourly value signal sets timing; an intercept enforces the declared price
    level. Bounds prevent a supposedly modest discount becoming a large subsidy
    or a discharge premium. This is a candidate family, not an optimal contract.
    """
    if not np.isfinite([lower, upper]).all() or not lower <= level <= upper:
        raise ValueError("Mean credit must lie within finite lower/upper credit bounds")
    credit = pd.Series(level, index=signal.index, dtype=float)
    if level in (lower, upper):
        return credit
    months = signal.index.tz_convert("Europe/Copenhagen").strftime("%Y-%m")
    for _, group in signal.groupby(months):
        raw = scale * (group - group.mean())
        if not np.isfinite(raw).all():
            raise ValueError("Scaled tariff signal must be finite")
        lo, hi = lower - float(raw.max()), upper - float(raw.min())
        for _ in range(80):
            intercept = (lo + hi) / 2
            if np.clip(raw + intercept, lower, upper).mean() < level:
                lo = intercept
            else:
                hi = intercept
        credit.loc[group.index] = np.clip(raw + (lo + hi) / 2, lower, upper)
    return credit


def direct_tariff(central, spec):
    """Freeze the direct-heat price from the central result for the response test."""
    basis = spec.get("direct_basis", "monthly_reference")
    reference = central.dispatch.reference_tariff_dkk_mwh
    if basis == "monthly_reference":
        return reference.copy()
    marginal = value_signals(central).conditional_delivered_heat_value_dkk_mwh
    if basis == "delivered_marginal":
        return marginal.copy()
    if basis == "monthly_mean_matched_marginal":
        return reference + marginal - _monthly_mean(marginal)
    raise ValueError("Unknown direct heat price basis: " + basis)


def value_signals(central):
    """Marginal delivered heat avoided less inventory opportunity cost, in DKK/MWh.

    If discharge replaces direct supply, the conditional system saving is
    mu_cph/r - v_inventory/eta_d - pumping. HTF sees credit - pumping.
    Equating these gives credit = mu_cph/r - v_inventory/eta_d. Constraints,
    integer changes and endogenous HP operation prevent a global implementation claim.
    """
    d = central.dispatch
    required = ["conditional_delivered_heat_value_dkk_mwh", "conditional_inventory_value_dkk_mwh"]
    if not all(k in d for k in required) or not np.isfinite(d[required]).all().all():
        raise ValueError("Value-based tariffs need a coordinated solve with conditional prices")
    eta = central.summary["assumptions"]["ptes"]["discharge_efficiency"]
    result = d[required].copy()
    result["discharge_value_spread_dkk_mwh"] = d[required[0]] - d[required[1]] / eta
    result["discharge_pump_cost_dkk_mwh_heat"] = d.discharge_pump_cost_dkk_mwh_heat
    result["conditional_net_discharge_value_dkk_mwh"] = (
        result.discharge_value_spread_dkk_mwh - d.discharge_pump_cost_dkk_mwh_heat
    )
    return result


def candidate_credit(central, spec):
    """Constant, scaled value spread, or monthly mean-matched value spread.

    No silent clipping: a negative credit is a discharge premium. Mean matching
    controls the arithmetic monthly level on the evaluated hours, not heat revenue.
    """
    family = spec["family"]
    level, scale = float(spec.get("level", 0.0)), float(spec.get("scale", 1.0))
    if not np.isfinite([level, scale]).all():
        raise ValueError("Tariff level and scale must be finite")
    if family in ("heat_value_price", "inventory_value_price"):
        signals = value_signals(central)
        if family == "heat_value_price":
            discharge_price = signals.conditional_delivered_heat_value_dkk_mwh
        else:
            eta = central.summary["assumptions"]["ptes"]["discharge_efficiency"]
            discharge_price = signals.conditional_inventory_value_dkk_mwh / eta
        # These families specify an absolute discharge-service price, rather
        # than assuming that a supplied discount is the economic foundation.
        price = level + scale * discharge_price
        return (direct_tariff(central, spec) - price).rename("discharge_discount_dkk_mwh")
    if family == "shared_value":
        # HTF receives a share (scale) of the positive storage value spread as its
        # discharge credit; hours where holding heat is worth more give no credit.
        signal = value_signals(central).discharge_value_spread_dkk_mwh
        upper = float(spec.get("upper", np.inf))
        credit = (scale * signal).clip(lower=float(spec.get("lower", 0.0)), upper=upper)
        return credit.rename("discharge_discount_dkk_mwh")
    credit = pd.Series(level, index=central.dispatch.index, dtype=float)
    if family != "constant":
        signal = value_signals(central).discharge_value_spread_dkk_mwh
        if family == "bounded_mean_matched_value":
            credit = _bounded_mean_credit(
                signal,
                level=level,
                scale=scale,
                lower=float(spec.get("lower", 0)),
                upper=float(spec.get("upper", 10)),
            )
            return credit.rename("discharge_discount_dkk_mwh")
        if family == "monthly_mean_matched_value":
            signal = signal - _monthly_mean(signal)
        elif family != "marginal_value":
            raise ValueError("Unknown tariff family: " + family)
        credit += scale * signal
    return credit.rename("discharge_discount_dkk_mwh")


def candidate_prices(central, spec):
    """Explicit direct and discharge prices; the discount is a settlement identity.

    With direct_basis=delivered_marginal and family=inventory_value_price,
    tau_H=mu/r and pi_D=v/eta_d. HTF pays discharge pumping separately.
    No cost-recovery or global decentralisation guarantee is implied.
    """
    direct = direct_tariff(central, spec)
    credit = candidate_credit(central, spec)
    return pd.DataFrame(
        {
            "reference_tariff_dkk_mwh": direct,
            "discharge_service_price_dkk_mwh": direct - credit,
            "discharge_discount_dkk_mwh": credit,
        }
    )
