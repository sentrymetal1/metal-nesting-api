"""
1D Linear Nesting - First Fit Decreasing + Local Swap Optimization
Stock matching: form_type + material_origin
  - form_type:      e.g. "Structural And Pipe", "Flat"
  - material_origin: e.g. "Carbon Steel", "Aluminum", "Stainless Steel"
    (comes from Specification.Material_Type_Origin in Zoho)
    Any new values added to Zoho core tables are captured automatically.
"""


def nest_1d(parts, stock_options, kerf):
    """
    parts: list of dicts:
        {
            "part_mark":       "A1",
            "bom_line_id":     "12345",
            "form_type":       "Structural And Pipe",
            "material_type":   "Angle",        # display only
            "material_origin": "Carbon Steel", # used for stock matching
            "spec_name":       "A36",          # display only
            "density":         0.2833,
            "length_in":       48.5,
            "quantity":        4
        }

    stock_options: list of dicts:
        {
            "stock_id":        "STK-001",
            "stock_label":     "Structural And Pipe | Carbon Steel | 20ft",
            "form_type":       "Structural And Pipe",
            "material_origin": "Carbon Steel",
            "density":         0.2833,
            "length_in":       240.0,
            "thickness_in":    0.25,
            "width_in":        2.0,
            "is_standard":     True
        }
    """

    # Group parts by form_type + material_origin
    # This means all Angle, Channel, Beam etc. of same origin nest from same stock pool
    groups = {}
    for part in parts:
        key = (part["form_type"], part["material_origin"])
        if key not in groups:
            groups[key] = {
                "cuts":    [],
                "density": part.get("density", 0)
            }
        for _ in range(int(part["quantity"])):
            groups[key]["cuts"].append({
                "part_mark":     part["part_mark"],
                "bom_line_id":   part["bom_line_id"],
                "material_type": part.get("material_type", ""),
                "spec_name":     part.get("spec_name", ""),
                "length_in":     float(part["length_in"])
            })

    stock_results = []
    stock_sequence = 1

    for (form_type, mat_origin), group_data in groups.items():
        cuts    = group_data["cuts"]
        density = group_data["density"]

        # Match stock by form_type + material_origin (case-insensitive, trimmed)
        matching_stock = [
            s for s in stock_options
            if s["form_type"].strip().lower() == form_type.strip().lower()
            and s["material_origin"].strip().lower() == mat_origin.strip().lower()
        ]

        if not matching_stock:
            stock_results.append({
                "error":           f"No stock found in library for: {form_type} | {mat_origin}. Add a matching record to Nesting_Stock_Library.",
                "form_type":       form_type,
                "material_origin": mat_origin
            })
            continue

        # Sort cuts largest first (FFD)
        cuts_sorted = sorted(cuts, key=lambda c: c["length_in"], reverse=True)
        max_cut     = max(c["length_in"] for c in cuts_sorted)

        # Find viable stock — must accommodate the largest part
        viable_stock = [
            s for s in matching_stock
            if float(s["length_in"]) >= max_cut
        ]

        if not viable_stock:
            stock_results.append({
                "error":           f"No stock long enough for {form_type} | {mat_origin}. Largest part: {max_cut}\". Add a longer stock size to Nesting_Stock_Library.",
                "form_type":       form_type,
                "material_origin": mat_origin
            })
            continue

        # Prefer shorter stock first to minimise offcuts
        viable_stock_sorted = sorted(viable_stock, key=lambda s: float(s["length_in"]))
        chosen_stock        = viable_stock_sorted[0]
        stock_length        = float(chosen_stock["length_in"])

        # --- First Fit Decreasing packing ---
        bins = []
        for cut in cuts_sorted:
            placed = False
            for b in bins:
                if b["remaining"] >= cut["length_in"] + kerf:
                    b["cuts"].append({
                        "part_mark":     cut["part_mark"],
                        "bom_line_id":   cut["bom_line_id"],
                        "material_type": cut["material_type"],
                        "spec_name":     cut["spec_name"],
                        "cut_length":    cut["length_in"],
                        "kerf":          kerf
                    })
                    b["remaining"] -= (cut["length_in"] + kerf)
                    placed = True
                    break
            if not placed:
                bins.append({
                    "remaining": stock_length - cut["length_in"] - kerf,
                    "cuts": [{
                        "part_mark":     cut["part_mark"],
                        "bom_line_id":   cut["bom_line_id"],
                        "material_type": cut["material_type"],
                        "spec_name":     cut["spec_name"],
                        "cut_length":    cut["length_in"],
                        "kerf":          kerf
                    }]
                })

        # --- Local swap optimisation ---
        bins = _optimize_1d_bins(bins, stock_length, kerf)

        # --- Build result records ---
        for b in bins:
            used_length = stock_length - b["remaining"]
            waste_pct   = round((b["remaining"] / stock_length) * 100, 2)
            weight      = _calc_weight_1d(chosen_stock, used_length, density)

            # Group cuts by part_mark + length for cut summary
            cut_summary = {}
            for c in b["cuts"]:
                k = (c["part_mark"], c["cut_length"])
                if k not in cut_summary:
                    cut_summary[k] = {
                        "part_mark":              c["part_mark"],
                        "bom_line_id":            c["bom_line_id"],
                        "material_type":          c["material_type"],
                        "spec_name":              c["spec_name"],
                        "cut_length":             c["cut_length"],
                        "quantity_on_this_stock": 0,
                        "cut_sequence":           len(cut_summary) + 1
                    }
                cut_summary[k]["quantity_on_this_stock"] += 1

            stock_results.append({
                "stock_sequence":    stock_sequence,
                "nesting_type":      "1D - Length",
                "form_type":         form_type,
                "material_origin":   mat_origin,
                "stock_id":          chosen_stock["stock_id"],
                "stock_label":       chosen_stock["stock_label"],
                "stock_length_in":   stock_length,
                "stock_width_in":    None,
                "remnant_length_in": round(b["remaining"], 4),
                "waste_percentage":  waste_pct,
                "stock_weight_lbs":  round(weight, 3),
                "cuts":              list(cut_summary.values())
            })
            stock_sequence += 1

    return stock_results


def _optimize_1d_bins(bins, stock_length, kerf):
    """Multi-pass local swap — consolidate cuts to reduce total stock count."""
    improved = True
    while improved:
        improved = False
        for i in range(len(bins)):
            for j in range(len(bins)):
                if i == j:
                    continue
                for cut in list(bins[i]["cuts"]):
                    needed = cut["cut_length"] + kerf
                    if bins[j]["remaining"] >= needed:
                        bins[j]["cuts"].append(cut)
                        bins[j]["remaining"] -= needed
                        bins[i]["cuts"].remove(cut)
                        bins[i]["remaining"] += needed
                        improved = True
                        break
        bins = [b for b in bins if b["cuts"]]
    return bins


def _calc_weight_1d(stock, used_length_in, density):
    """Weight using Nominal_Density from Material_Type lookup."""
    if not density or density == 0:
        return 0
    area_in2  = float(stock.get("area_in2", 0) or 0)
    thickness = float(stock.get("thickness_in", 0) or 0)
    width     = float(stock.get("width_in", 0) or 0)
    if area_in2 > 0:
        return used_length_in * area_in2 * density
    if thickness > 0 and width > 0:
        return used_length_in * thickness * width * density
    return 0
