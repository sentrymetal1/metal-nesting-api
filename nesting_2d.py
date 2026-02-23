"""
2D Panel Nesting - Guillotine Cut Algorithm
Stock matching: form_type + material_origin
  - material_origin: e.g. "Carbon Steel", "Aluminum", "Stainless Steel"
    (from Specification.Material_Type_Origin — fully data-driven)
"""


def nest_2d(parts, stock_options, kerf):
    """
    parts: list of dicts:
        {
            "part_mark":       "P1",
            "bom_line_id":     "12345",
            "form_type":       "Flat",
            "material_type":   "Plate",        # display only
            "material_origin": "Carbon Steel", # used for stock matching
            "spec_name":       "A36",          # display only
            "density":         0.2833,
            "length_in":       24.0,
            "width_in":        12.0,
            "thickness_in":    0.25,
            "quantity":        3,
            "grain_direction": "none"
        }
    """

    # Group by form_type + material_origin + thickness
    groups = {}
    for part in parts:
        key = (part["form_type"], part["material_origin"], float(part["thickness_in"]))
        if key not in groups:
            groups[key] = {"parts": [], "density": part.get("density", 0)}
        for _ in range(int(part["quantity"])):
            groups[key]["parts"].append({
                "part_mark":      part["part_mark"],
                "bom_line_id":    part["bom_line_id"],
                "material_type":  part.get("material_type", ""),
                "spec_name":      part.get("spec_name", ""),
                "length_in":      float(part["length_in"]),
                "width_in":       float(part["width_in"]),
                "grain_direction": part.get("grain_direction", "none").lower()
            })

    stock_results = []
    stock_sequence = 1

    for (form_type, mat_origin, thickness), group_data in groups.items():
        parts_group = group_data["parts"]
        density     = group_data["density"]

        # Match stock by form_type + material_origin + thickness
        matching_stock = [
            s for s in stock_options
            if s["form_type"].strip().lower() == form_type.strip().lower()
            and s["material_origin"].strip().lower() == mat_origin.strip().lower()
            and abs(float(s.get("thickness_in", 0)) - thickness) < 0.001
        ]

        # Fallback: match without thickness
        if not matching_stock:
            matching_stock = [
                s for s in stock_options
                if s["form_type"].strip().lower() == form_type.strip().lower()
                and s["material_origin"].strip().lower() == mat_origin.strip().lower()
            ]

        if not matching_stock:
            stock_results.append({
                "error":           f"No panel stock found for {form_type} | {mat_origin} | {thickness}\" thk. Add to Nesting_Stock_Library.",
                "form_type":       form_type,
                "material_origin": mat_origin
            })
            continue

        # Sort largest area first
        parts_sorted = sorted(
            parts_group,
            key=lambda p: p["length_in"] * p["width_in"],
            reverse=True
        )

        max_l = max(p["length_in"] for p in parts_sorted)
        max_w = max(p["width_in"] for p in parts_sorted)

        viable_stock = [
            s for s in matching_stock
            if float(s["length_in"]) >= max_l and float(s["width_in"]) >= max_w
        ]
        if not viable_stock:
            viable_stock = [
                s for s in matching_stock
                if float(s["length_in"]) >= max_w and float(s["width_in"]) >= max_l
            ]

        if not viable_stock:
            stock_results.append({
                "error":           f"No panel large enough for {form_type} | {mat_origin} — largest part {max_l}×{max_w}\". Add larger stock to Nesting_Stock_Library.",
                "form_type":       form_type,
                "material_origin": mat_origin
            })
            continue

        viable_stock_sorted = sorted(
            viable_stock,
            key=lambda s: float(s["length_in"]) * float(s["width_in"])
        )
        chosen_stock = viable_stock_sorted[0]
        stock_l      = float(chosen_stock["length_in"])
        stock_w      = float(chosen_stock["width_in"])

        # --- Guillotine packing ---
        sheets = []
        for part in parts_sorted:
            placed = False
            for sheet in sheets:
                result = _guillotine_place(sheet["free_rects"], part, kerf)
                if result:
                    x, y, rotated = result
                    sheet["cuts"].append(_make_cut(part, x, y, rotated))
                    placed = True
                    break
            if not placed:
                new_sheet = {
                    "free_rects": [{"x": 0, "y": 0, "l": stock_l, "w": stock_w}],
                    "cuts": []
                }
                result = _guillotine_place(new_sheet["free_rects"], part, kerf)
                if result:
                    x, y, rotated = result
                    new_sheet["cuts"].append(_make_cut(part, x, y, rotated))
                    sheets.append(new_sheet)

        # --- Build result records ---
        for sheet in sheets:
            used_area   = sum(c["cut_length"] * c["cut_width"] for c in sheet["cuts"])
            total_area  = stock_l * stock_w
            remnant_area = total_area - used_area
            waste_pct   = round((remnant_area / total_area) * 100, 2)

            max_x     = max((c["x_position"] + c["cut_length"]) for c in sheet["cuts"]) if sheet["cuts"] else 0
            max_y     = max((c["y_position"] + c["cut_width"])  for c in sheet["cuts"]) if sheet["cuts"] else 0
            remnant_l = round(stock_l - max_x, 4)
            remnant_w = round(stock_w - max_y, 4)

            weight = _calc_weight_2d(density, used_area, thickness)
            svg    = _generate_svg(sheet["cuts"], stock_l, stock_w, kerf)

            cut_summary = {}
            for c in sheet["cuts"]:
                k = (c["part_mark"], c["cut_length"], c["cut_width"])
                if k not in cut_summary:
                    cut_summary[k] = {**c, "quantity_on_this_stock": 0, "cut_sequence": len(cut_summary) + 1}
                cut_summary[k]["quantity_on_this_stock"] += 1

            stock_results.append({
                "stock_sequence":    stock_sequence,
                "nesting_type":      "2D - Panel",
                "form_type":         form_type,
                "material_origin":   mat_origin,
                "thickness_in":      thickness,
                "stock_id":          chosen_stock["stock_id"],
                "stock_label":       chosen_stock["stock_label"],
                "stock_length_in":   stock_l,
                "stock_width_in":    stock_w,
                "remnant_length_in": remnant_l,
                "remnant_width_in":  remnant_w,
                "remnant_area_in2":  round(remnant_area, 4),
                "waste_percentage":  waste_pct,
                "stock_weight_lbs":  round(weight, 3),
                "svg_layout":        svg,
                "cuts":              list(cut_summary.values())
            })
            stock_sequence += 1

    return stock_results


def _make_cut(part, x, y, rotated):
    return {
        "part_mark":             part["part_mark"],
        "bom_line_id":           part["bom_line_id"],
        "material_type":         part.get("material_type", ""),
        "spec_name":             part.get("spec_name", ""),
        "cut_length":            part["length_in"],
        "cut_width":             part["width_in"],
        "x_position":            round(x, 4),
        "y_position":            round(y, 4),
        "rotation":              "90°" if rotated else "0°",
        "quantity_on_this_stock": 1
    }


def _guillotine_place(free_rects, part, kerf):
    best = None
    best_area = float("inf")
    part_l = part["length_in"]
    part_w = part["width_in"]
    grain  = part.get("grain_direction", "none")

    for rect in free_rects:
        rl, rw = rect["l"], rect["w"]
        if rl >= part_l + kerf and rw >= part_w + kerf:
            area = rl * rw
            if area < best_area:
                best = (rect, False)
                best_area = area
        if grain == "none":
            if rl >= part_w + kerf and rw >= part_l + kerf:
                area = rl * rw
                if area < best_area:
                    best = (rect, True)
                    best_area = area

    if not best:
        return None

    rect, rotated = best
    x, y = rect["x"], rect["y"]
    placed_l = part_w if rotated else part_l
    placed_w = part_l if rotated else part_w

    free_rects.remove(rect)
    right_l = rect["l"] - placed_l - kerf
    if right_l > kerf:
        free_rects.append({"x": x + placed_l + kerf, "y": y, "l": right_l, "w": rect["w"]})
    top_w = rect["w"] - placed_w - kerf
    if top_w > kerf:
        free_rects.append({"x": x, "y": y + placed_w + kerf, "l": placed_l, "w": top_w})

    return x, y, rotated


def _calc_weight_2d(density, used_area_in2, thickness):
    if density and density > 0 and thickness and thickness > 0:
        return used_area_in2 * thickness * density
    return 0


def _generate_svg(cuts, stock_l, stock_w, kerf, scale=4):
    svg_w = stock_l * scale
    svg_h = stock_w * scale
    colors = ["#4E9AF1","#F1A04E","#4EF16A","#F14E4E","#A04EF1","#F1E24E","#4EF1E2","#F14EA0","#7EF14E","#F17E4E"]
    part_colors = {}
    color_idx = 0
    rects = []
    for cut in cuts:
        pm = cut["part_mark"]
        if pm not in part_colors:
            part_colors[pm] = colors[color_idx % len(colors)]
            color_idx += 1
        x = cut["x_position"] * scale
        y = cut["y_position"] * scale
        w = cut["cut_length"] * scale
        h = cut["cut_width"] * scale
        color = part_colors[pm]
        label = f"{pm} {cut['cut_length']}x{cut['cut_width']}\""
        rects.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{color}" stroke="#333" stroke-width="1" opacity="0.85"/>'
            f'<text x="{x+w/2}" y="{y+h/2}" text-anchor="middle" dominant-baseline="middle" font-size="10" fill="#111">{label}</text>'
        )
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}"><rect width="{svg_w}" height="{svg_h}" fill="#e8e8e8" stroke="#999" stroke-width="2"/>{"".join(rects)}</svg>'
