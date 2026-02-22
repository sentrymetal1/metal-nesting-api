"""
2D Panel Nesting - Guillotine Cut Algorithm with Grain Direction Support
Handles: Plate, Sheet
Produces X/Y position data for SVG rendering in Zoho Creator
"""


def nest_2d(parts, stock_options, kerf):
    """
    Nest 2D rectangular parts onto panel stock using guillotine cuts.

    parts: list of dicts:
        {
            "part_mark":      "P1",
            "bom_line_id":    "12345",
            "material_type":  "Plate",
            "material_grade": "A36",
            "length_in":      24.0,
            "width_in":       12.0,
            "thickness_in":   0.25,
            "quantity":       3,
            "grain_direction": "horizontal"  # or "vertical" or "none"
        }

    stock_options: list of dicts:
        {
            "stock_id":       "STK-010",
            "stock_label":    "Plate | A36 | 48x96",
            "material_type":  "Plate",
            "material_grade": "A36",
            "length_in":      96.0,
            "width_in":       48.0,
            "thickness_in":   0.25,
            "is_standard":    True,
            "density":        0.2833
        }

    Returns list of stock result dicts with cut positions for SVG rendering.
    """

    # Group parts by material_type + material_grade + thickness
    groups = {}
    for part in parts:
        key = (part["material_type"], part["material_grade"], float(part["thickness_in"]))
        if key not in groups:
            groups[key] = []
        for _ in range(int(part["quantity"])):
            groups[key].append({
                "part_mark":      part["part_mark"],
                "bom_line_id":    part["bom_line_id"],
                "length_in":      float(part["length_in"]),
                "width_in":       float(part["width_in"]),
                "grain_direction": part.get("grain_direction", "none").lower()
            })

    stock_results = []
    stock_sequence = 1

    for (mat_type, mat_grade, thickness), parts_group in groups.items():
        # Find matching stock
        matching_stock = [
            s for s in stock_options
            if s["material_type"] == mat_type
            and s["material_grade"] == mat_grade
            and abs(float(s["thickness_in"]) - thickness) < 0.001
        ]

        if not matching_stock:
            matching_stock = [
                s for s in stock_options
                if s["material_type"] == mat_type
                and abs(float(s["thickness_in"]) - thickness) < 0.001
            ]

        if not matching_stock:
            continue

        # Sort parts largest area first
        parts_sorted = sorted(
            parts_group,
            key=lambda p: p["length_in"] * p["width_in"],
            reverse=True
        )

        # Choose stock — prefer smallest sheet that fits the largest part
        max_l = max(p["length_in"] for p in parts_sorted)
        max_w = max(p["width_in"] for p in parts_sorted)

        viable_stock = [
            s for s in matching_stock
            if float(s["length_in"]) >= max_l and float(s["width_in"]) >= max_w
        ]

        if not viable_stock:
            # Try rotated
            viable_stock = [
                s for s in matching_stock
                if float(s["length_in"]) >= max_w and float(s["width_in"]) >= max_l
            ]

        if not viable_stock:
            stock_results.append({
                "error": f"No panel large enough for {mat_type} {mat_grade} {thickness}\" part {max_l}x{max_w}in",
                "material_type": mat_type,
                "material_grade": mat_grade
            })
            continue

        # Prefer smaller sheets first
        viable_stock_sorted = sorted(
            viable_stock,
            key=lambda s: float(s["length_in"]) * float(s["width_in"])
        )
        chosen_stock = viable_stock_sorted[0]

        stock_l = float(chosen_stock["length_in"])
        stock_w = float(chosen_stock["width_in"])

        # --- Guillotine Packing ---
        sheets = []  # Each sheet = one stock panel

        for part in parts_sorted:
            placed = False
            for sheet in sheets:
                result = _guillotine_place(sheet["free_rects"], part, kerf)
                if result:
                    x, y, rotated = result
                    placed_l = part["width_in"] if rotated else part["length_in"]
                    placed_w = part["length_in"] if rotated else part["width_in"]
                    sheet["cuts"].append({
                        "part_mark":              part["part_mark"],
                        "bom_line_id":            part["bom_line_id"],
                        "cut_length":             part["length_in"],
                        "cut_width":              part["width_in"],
                        "x_position":             round(x, 4),
                        "y_position":             round(y, 4),
                        "rotation":               "90°" if rotated else "0°",
                        "quantity_on_this_stock": 1
                    })
                    placed = True
                    break

            if not placed:
                # Start a new sheet
                new_sheet = {
                    "free_rects": [{"x": 0, "y": 0, "l": stock_l, "w": stock_w}],
                    "cuts": []
                }
                result = _guillotine_place(new_sheet["free_rects"], part, kerf)
                if result:
                    x, y, rotated = result
                    new_sheet["cuts"].append({
                        "part_mark":              part["part_mark"],
                        "bom_line_id":            part["bom_line_id"],
                        "cut_length":             part["length_in"],
                        "cut_width":              part["width_in"],
                        "x_position":             round(x, 4),
                        "y_position":             round(y, 4),
                        "rotation":               "90°" if rotated else "0°",
                        "quantity_on_this_stock": 1
                    })
                    sheets.append(new_sheet)

        # --- Build result records ---
        for sheet in sheets:
            used_area = sum(
                c["cut_length"] * c["cut_width"] for c in sheet["cuts"]
            )
            total_area = stock_l * stock_w
            remnant_area = total_area - used_area
            waste_pct = round((remnant_area / total_area) * 100, 2)

            # Bounding box of used area for remnant estimate
            max_x = max((c["x_position"] + c["cut_length"]) for c in sheet["cuts"]) if sheet["cuts"] else 0
            max_y = max((c["y_position"] + c["cut_width"]) for c in sheet["cuts"]) if sheet["cuts"] else 0
            remnant_l = round(stock_l - max_x, 4)
            remnant_w = round(stock_w - max_y, 4)

            weight = _calc_weight_2d(chosen_stock, used_area)

            # Consolidate cuts with same part_mark + dimensions
            cut_summary = {}
            for c in sheet["cuts"]:
                k = (c["part_mark"], c["cut_length"], c["cut_width"])
                if k not in cut_summary:
                    cut_summary[k] = {**c, "quantity_on_this_stock": 0,
                                      "cut_sequence": len(cut_summary) + 1}
                cut_summary[k]["quantity_on_this_stock"] += 1

            svg = _generate_svg(sheet["cuts"], stock_l, stock_w, kerf)

            stock_results.append({
                "stock_sequence":    stock_sequence,
                "nesting_type":      "2D - Panel",
                "material_type":     mat_type,
                "material_grade":    mat_grade,
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
                "cuts": list(cut_summary.values())
            })
            stock_sequence += 1

    return stock_results


def _guillotine_place(free_rects, part, kerf):
    """
    Try to place a part into the best fitting free rectangle.
    Returns (x, y, rotated) or None if it doesn't fit.
    Respects grain direction — only rotates if grain == 'none'.
    """
    best = None
    best_area = float("inf")

    part_l = part["length_in"]
    part_w = part["width_in"]
    grain = part.get("grain_direction", "none")

    for rect in free_rects:
        rl, rw = rect["l"], rect["w"]

        # Try normal orientation
        if rl >= part_l + kerf and rw >= part_w + kerf:
            area = rl * rw
            if area < best_area:
                best = (rect, False)
                best_area = area

        # Try rotated (only if grain allows)
        if grain == "none":
            if rl >= part_w + kerf and rw >= part_l + kerf:
                area = rl * rw
                if area < best_area:
                    best = (rect, True)
                    best_area = area

    if not best:
        return None

    rect, rotated = best
    x = rect["x"]
    y = rect["y"]

    placed_l = part_w if rotated else part_l
    placed_w = part_l if rotated else part_w

    # Guillotine split — split remaining space into two rectangles
    free_rects.remove(rect)

    # Right remainder
    right_l = rect["l"] - placed_l - kerf
    if right_l > kerf:
        free_rects.append({
            "x": x + placed_l + kerf,
            "y": y,
            "l": right_l,
            "w": rect["w"]
        })

    # Top remainder
    top_w = rect["w"] - placed_w - kerf
    if top_w > kerf:
        free_rects.append({
            "x": x,
            "y": y + placed_w + kerf,
            "l": placed_l,
            "w": top_w
        })

    return x, y, rotated


def _calc_weight_2d(stock, used_area_in2):
    density = stock.get("density", 0)
    thickness = float(stock.get("thickness_in", 0))
    if density and thickness:
        return used_area_in2 * thickness * density
    return 0


def _generate_svg(cuts, stock_l, stock_w, kerf, scale=4):
    """
    Generate an SVG string showing the cut layout on a panel.
    Scale: pixels per inch (default 4px/in — adjust for display size).
    """
    svg_w = stock_l * scale
    svg_h = stock_w * scale

    # Color palette for different parts
    colors = [
        "#4E9AF1", "#F1A04E", "#4EF16A", "#F14E4E",
        "#A04EF1", "#F1E24E", "#4EF1E2", "#F14EA0"
    ]
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
        label = f"{pm} {cut['cut_length']}x{cut['cut_width']}"

        rects.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
            f'fill="{color}" stroke="#333" stroke-width="1" opacity="0.85"/>'
            f'<text x="{x + w/2}" y="{y + h/2}" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="10" fill="#111">{label}</text>'
        )

    rects_svg = "\n  ".join(rects)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}">
  <rect width="{svg_w}" height="{svg_h}" fill="#e8e8e8" stroke="#999" stroke-width="2"/>
  {rects_svg}
</svg>"""

    return svg
