"""
1D Linear Nesting - First Fit Decreasing + Local Swap Optimization
Handles: Angle, Channel, Beam, Bar, Pipe, Tube
"""


def nest_1d(parts, stock_options, kerf):
    """
    Nest 1D parts onto stock lengths.

    parts: list of dicts:
        {
            "part_mark":    "A1",
            "bom_line_id":  "12345",
            "material_type": "Angle",
            "material_grade": "A36",
            "length_in":    48.5,
            "quantity":     4
        }

    stock_options: list of dicts:
        {
            "stock_id":      "STK-001",
            "stock_label":   "Angle | A36 | 240in (20ft)",
            "material_type": "Angle",
            "material_grade": "A36",
            "length_in":     240.0,
            "is_standard":   True,
            "density":       0.2833
        }

    Returns list of stock result dicts.
    """

    # Group parts by material_type + material_grade
    groups = {}
    for part in parts:
        key = (part["material_type"], part["material_grade"])
        if key not in groups:
            groups[key] = []
        # Expand quantity into individual cut entries
        for _ in range(int(part["quantity"])):
            groups[key].append({
                "part_mark":   part["part_mark"],
                "bom_line_id": part["bom_line_id"],
                "length_in":   float(part["length_in"])
            })

    stock_results = []
    stock_sequence = 1

    for (mat_type, mat_grade), cuts in groups.items():
        # Find matching stock options for this material group
        matching_stock = [
            s for s in stock_options
            if s["material_type"] == mat_type and s["material_grade"] == mat_grade
        ]

        if not matching_stock:
            # Fallback: use the largest available stock of this material type
            matching_stock = [
                s for s in stock_options
                if s["material_type"] == mat_type
            ]

        if not matching_stock:
            continue  # No stock available for this material — skip

        # Sort cuts largest first (FFD)
        cuts_sorted = sorted(cuts, key=lambda c: c["length_in"], reverse=True)

        # Choose optimal stock length — prefer shorter stock that still fits largest part
        max_cut = max(c["length_in"] for c in cuts_sorted)
        viable_stock = [s for s in matching_stock if s["length_in"] >= max_cut]

        if not viable_stock:
            # No single stock fits the largest part — flag it
            stock_results.append({
                "error": f"No stock long enough for {mat_type} {mat_grade} part of {max_cut}in",
                "material_type": mat_type,
                "material_grade": mat_grade
            })
            continue

        # Prioritize shorter stock first to minimize offcuts
        viable_stock_sorted = sorted(viable_stock, key=lambda s: s["length_in"])
        chosen_stock = viable_stock_sorted[0]

        # --- First Fit Decreasing packing ---
        bins = []  # Each bin = one stock piece
        for cut in cuts_sorted:
            placed = False
            for b in bins:
                if b["remaining"] >= cut["length_in"] + kerf:
                    b["cuts"].append({
                        "part_mark":    cut["part_mark"],
                        "bom_line_id":  cut["bom_line_id"],
                        "cut_length":   cut["length_in"],
                        "kerf":         kerf
                    })
                    b["remaining"] -= (cut["length_in"] + kerf)
                    placed = True
                    break
            if not placed:
                new_bin = {
                    "remaining": chosen_stock["length_in"] - cut["length_in"] - kerf,
                    "cuts": [{
                        "part_mark":   cut["part_mark"],
                        "bom_line_id": cut["bom_line_id"],
                        "cut_length":  cut["length_in"],
                        "kerf":        kerf
                    }]
                }
                bins.append(new_bin)

        # --- Local Swap Optimization ---
        bins = _optimize_1d_bins(bins, chosen_stock["length_in"], kerf)

        # --- Build result records ---
        for i, b in enumerate(bins):
            used = chosen_stock["length_in"] - b["remaining"]
            waste_pct = round((b["remaining"] / chosen_stock["length_in"]) * 100, 2)

            # Group cuts by part_mark + length for summary
            cut_summary = {}
            for c in b["cuts"]:
                k = (c["part_mark"], c["cut_length"])
                if k not in cut_summary:
                    cut_summary[k] = {"part_mark": c["part_mark"],
                                      "bom_line_id": c["bom_line_id"],
                                      "cut_length": c["cut_length"],
                                      "quantity_on_this_stock": 0,
                                      "cut_sequence": len(cut_summary) + 1}
                cut_summary[k]["quantity_on_this_stock"] += 1

            # Weight calculation
            weight = _calc_weight_1d(chosen_stock, used)

            stock_results.append({
                "stock_sequence":   stock_sequence,
                "nesting_type":     "1D - Length",
                "material_type":    mat_type,
                "material_grade":   mat_grade,
                "stock_id":         chosen_stock["stock_id"],
                "stock_label":      chosen_stock["stock_label"],
                "stock_length_in":  chosen_stock["length_in"],
                "stock_width_in":   None,
                "remnant_length_in": round(b["remaining"], 4),
                "waste_percentage": waste_pct,
                "stock_weight_lbs": round(weight, 3),
                "cuts": list(cut_summary.values())
            })
            stock_sequence += 1

    return stock_results


def _optimize_1d_bins(bins, stock_length, kerf):
    """
    Local swap optimization — try to eliminate bins by moving cuts between them.
    Runs multiple passes until no improvement is found.
    """
    improved = True
    while improved:
        improved = False
        for i in range(len(bins)):
            for j in range(len(bins)):
                if i == j:
                    continue
                # Try to move each cut from bin i into bin j
                for cut in list(bins[i]["cuts"]):
                    needed = cut["cut_length"] + kerf
                    if bins[j]["remaining"] >= needed:
                        bins[j]["cuts"].append(cut)
                        bins[j]["remaining"] -= needed
                        bins[i]["cuts"].remove(cut)
                        bins[i]["remaining"] += needed
                        improved = True
                        break

        # Remove empty bins
        bins = [b for b in bins if b["cuts"]]

    return bins


def _calc_weight_1d(stock, used_length_in):
    """
    Estimate weight of used portion of stock.
    Uses density if provided, otherwise returns 0.
    """
    density = stock.get("density", 0)
    thickness = stock.get("thickness_in", 0)
    width = stock.get("width_in", 0)

    if density and thickness and width:
        # Flat bar or similar: L x W x T x density
        return used_length_in * width * thickness * density
    elif density and stock.get("area_in2", 0):
        # Structural shapes: use cross-section area
        return used_length_in * stock["area_in2"] * density

    return 0
