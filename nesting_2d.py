"""
2D Panel Nesting - Multi-Stock Guillotine Cut Algorithm
Algorithm:
  1. Sort all parts DESCENDING by area (largest first)
  2. For each part, find the smallest stock panel that fits it
  3. Try to pack it into an existing open sheet of that stock size
  4. If no sheet has room, open a new sheet at the smallest viable stock size
  5. Pack as many additional parts as possible into each sheet
  6. After all packing, downsize any sheet that could use smaller stock

Stock matching: form_type + material_origin
"""


def nest_2d(parts, stock_options, kerf):
    # Group by form_type + material_origin + thickness
    groups = {}
    for part in parts:
        key = (part["form_type"], part["material_origin"], float(part["thickness_in"]))
        if key not in groups:
            groups[key] = {"parts": [], "density": part.get("density", 0)}
        for _ in range(int(part["quantity"])):
            groups[key]["parts"].append({
                "part_mark":       part["part_mark"],
                "bom_line_id":     part["bom_line_id"],
                "material_type":   part.get("material_type", ""),
                "spec_name":       part.get("spec_name", ""),
                "length_in":       float(part["length_in"]),
                "width_in":        float(part["width_in"]),
                "grain_direction": part.get("grain_direction", "none").lower()
            })

    stock_results = []
    stock_sequence = 1

    for (form_type, mat_origin, thickness), group_data in groups.items():
        parts_group = group_data["parts"]
        density = group_data["density"]

        # Match stock by form_type + material_origin
        matching_stock = [
            s for s in stock_options
            if s["form_type"].strip().lower() == form_type.strip().lower()
            and s["material_origin"].strip().lower() == mat_origin.strip().lower()
        ]

        if not matching_stock:
            stock_results.append({
                "error": f"No panel stock found for {form_type} | {mat_origin} | {thickness}\" thk. Add to Nesting_Stock_Library.",
                "form_type": form_type,
                "material_origin": mat_origin
            })
            continue

        # Build stock lookup: (length, width) -> stock record, sorted by area ascending
        stock_by_key = {}
        for s in matching_stock:
            sl = float(s["length_in"])
            sw = float(s["width_in"])
            size_key = (sl, sw)
            if size_key not in stock_by_key:
                stock_by_key[size_key] = s
        available_sizes = sorted(stock_by_key.keys(), key=lambda k: k[0] * k[1])  # smallest first

        if not available_sizes:
            stock_results.append({
                "error": f"No viable panel stock for: {form_type} | {mat_origin}.",
                "form_type": form_type,
                "material_origin": mat_origin
            })
            continue

        # Sort parts by area descending (largest first)
        remaining_parts = sorted(
            parts_group,
            key=lambda p: p["length_in"] * p["width_in"],
            reverse=True
        )

        # Check if largest stock can fit the largest part
        max_part_l = max(p["length_in"] for p in remaining_parts)
        max_part_w = max(p["width_in"] for p in remaining_parts)
        largest_stock = available_sizes[-1]  # largest area
        can_fit = (
            (largest_stock[0] >= max_part_l and largest_stock[1] >= max_part_w) or
            (largest_stock[0] >= max_part_w and largest_stock[1] >= max_part_l)
        )
        if not can_fit:
            stock_results.append({
                "error": f"No panel large enough for {form_type} | {mat_origin} — largest part {max_part_l}×{max_part_w}\". Add larger stock.",
                "form_type": form_type,
                "material_origin": mat_origin
            })
            continue

        # --- Best-fit packing: for each part, find smallest stock that works ---
        sheets = []

        for part in remaining_parts:
            # Try to fit into an existing sheet (prefer sheet with least free area)
            placed = False
            best_sheet = None
            best_free_area = float("inf")

            for sheet in sheets:
                result = _guillotine_place(sheet["free_rects"], part, kerf, dry_run=True)
                if result:
                    free_area = sum(r["l"] * r["w"] for r in sheet["free_rects"])
                    if free_area < best_free_area:
                        best_sheet = sheet
                        best_free_area = free_area

            if best_sheet:
                result = _guillotine_place(best_sheet["free_rects"], part, kerf, dry_run=False)
                if result:
                    x, y, rotated = result
                    best_sheet["cuts"].append(_make_cut(part, x, y, rotated))
                    placed = True

            if not placed:
                # Open a new sheet — find smallest stock that fits this part
                chosen_size = None
                for (sl, sw) in available_sizes:  # sorted smallest first
                    if _part_fits_stock(part, sl, sw, kerf):
                        chosen_size = (sl, sw)
                        break

                if chosen_size is None:
                    stock_results.append({
                        "error": f"Part {part['part_mark']} ({part['length_in']}×{part['width_in']}\") too large for any stock in {form_type} | {mat_origin}.",
                        "form_type": form_type,
                        "material_origin": mat_origin
                    })
                    continue

                sl, sw = chosen_size
                new_sheet = {
                    "stock_l": sl,
                    "stock_w": sw,
                    "chosen_stock": stock_by_key[chosen_size],
                    "free_rects": [{"x": 0, "y": 0, "l": sl, "w": sw}],
                    "cuts": []
                }
                result = _guillotine_place(new_sheet["free_rects"], part, kerf, dry_run=False)
                if result:
                    x, y, rotated = result
                    new_sheet["cuts"].append(_make_cut(part, x, y, rotated))
                    sheets.append(new_sheet)

        # --- Optimization: try to consolidate sheets ---
        sheets = _optimize_sheets(sheets, kerf)

        # --- Final downsize: shrink each sheet to smallest viable stock ---
        sheets = _downsize_sheets(sheets, available_sizes, stock_by_key, kerf)

        # --- Build result records ---
        for sheet in sheets:
            stock_l = sheet["stock_l"]
            stock_w = sheet["stock_w"]
            chosen_stock = sheet["chosen_stock"]
            used_area = sum(c["cut_length"] * c["cut_width"] for c in sheet["cuts"])
            total_area = stock_l * stock_w
            remnant_area = total_area - used_area
            waste_pct = round((remnant_area / total_area) * 100, 2) if total_area > 0 else 0

            max_x = max((c["x_position"] + c["cut_length"]) for c in sheet["cuts"]) if sheet["cuts"] else 0
            max_y = max((c["y_position"] + c["cut_width"]) for c in sheet["cuts"]) if sheet["cuts"] else 0
            remnant_l = round(stock_l - max_x, 4)
            remnant_w = round(stock_w - max_y, 4)

            weight = _calc_weight_2d(density, used_area, thickness)
            svg = _generate_svg(sheet["cuts"], stock_l, stock_w, kerf)

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


def _part_fits_stock(part, stock_l, stock_w, kerf):
    """Check if a part can fit on a stock panel (with or without rotation)."""
    pl, pw = part["length_in"], part["width_in"]
    grain = part.get("grain_direction", "none")
    if stock_l >= pl + kerf and stock_w >= pw + kerf:
        return True
    if grain == "none":
        if stock_l >= pw + kerf and stock_w >= pl + kerf:
            return True
    return False


def _optimize_sheets(sheets, kerf):
    """Try to move all cuts from one sheet into others to eliminate sheets."""
    improved = True
    while improved:
        improved = False
        sheets.sort(key=lambda s: len(s["cuts"]))  # fewest cuts first
        for i in range(len(sheets)):
            if not sheets[i]["cuts"]:
                continue
            # Try to move ALL cuts from sheet[i] to other sheets
            moves = []
            all_moved = True
            # Work on a copy of free_rects for simulation
            for cut_info in sheets[i]["cuts"]:
                part = {
                    "length_in": cut_info["cut_length"],
                    "width_in": cut_info["cut_width"],
                    "grain_direction": "none" if cut_info.get("rotation") == "90°" else "length"
                }
                placed = False
                for j in range(len(sheets)):
                    if i == j:
                        continue
                    result = _guillotine_place(sheets[j]["free_rects"], part, kerf, dry_run=True)
                    if result:
                        moves.append((cut_info, j, part))
                        placed = True
                        break
                if not placed:
                    all_moved = False
                    break

            if all_moved and moves:
                for cut_info, target_idx, part in moves:
                    result = _guillotine_place(sheets[target_idx]["free_rects"], part, kerf, dry_run=False)
                    if result:
                        x, y, rotated = result
                        new_cut = {**cut_info, "x_position": round(x, 4), "y_position": round(y, 4)}
                        sheets[target_idx]["cuts"].append(new_cut)
                sheets[i]["cuts"] = []
                improved = True

        sheets = [s for s in sheets if s["cuts"]]
    return sheets


def _downsize_sheets(sheets, available_sizes, stock_by_key, kerf):
    """After packing, check if any sheet can use a smaller stock panel."""
    for sheet in sheets:
        if not sheet["cuts"]:
            continue
        # Find the bounding box of all placed cuts
        max_x = max(c["x_position"] + c["cut_length"] + kerf for c in sheet["cuts"])
        max_y = max(c["y_position"] + c["cut_width"] + kerf for c in sheet["cuts"])

        # Find smallest stock that fits the bounding box
        for (sl, sw) in available_sizes:  # sorted smallest first
            if sl >= max_x and sw >= max_y:
                if sl * sw < sheet["stock_l"] * sheet["stock_w"]:
                    sheet["stock_l"] = sl
                    sheet["stock_w"] = sw
                    sheet["chosen_stock"] = stock_by_key[(sl, sw)]
                break
            # Also check rotated stock
            if sw >= max_x and sl >= max_y:
                if sl * sw < sheet["stock_l"] * sheet["stock_w"]:
                    sheet["stock_l"] = sl
                    sheet["stock_w"] = sw
                    sheet["chosen_stock"] = stock_by_key[(sl, sw)]
                break

    return sheets


def _make_cut(part, x, y, rotated):
    return {
        "part_mark":              part["part_mark"],
        "bom_line_id":            part["bom_line_id"],
        "material_type":          part.get("material_type", ""),
        "spec_name":              part.get("spec_name", ""),
        "cut_length":             part["length_in"],
        "cut_width":              part["width_in"],
        "x_position":             round(x, 4),
        "y_position":             round(y, 4),
        "rotation":               "90°" if rotated else "0°",
        "quantity_on_this_stock":  1
    }


def _guillotine_place(free_rects, part, kerf, dry_run=False):
    """Find best free rectangle to place part using guillotine cuts.
    If dry_run=True, check if placement is possible without modifying free_rects."""
    best = None
    best_area = float("inf")
    part_l = part["length_in"]
    part_w = part["width_in"]
    grain = part.get("grain_direction", "none")

    for rect in free_rects:
        rl, rw = rect["l"], rect["w"]
        # Normal orientation
        if rl >= part_l + kerf and rw >= part_w + kerf:
            area = rl * rw
            if area < best_area:
                best = (rect, False)
                best_area = area
        # Rotated orientation (only if grain allows)
        if grain == "none":
            if rl >= part_w + kerf and rw >= part_l + kerf:
                area = rl * rw
                if area < best_area:
                    best = (rect, True)
                    best_area = area

    if not best:
        return None

    if dry_run:
        rect, rotated = best
        return rect["x"], rect["y"], rotated

    rect, rotated = best
    x, y = rect["x"], rect["y"]
    placed_l = part_w if rotated else part_l
    placed_w = part_l if rotated else part_w

    # Split remaining space (guillotine cut)
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
    colors = ["#4E9AF1", "#F1A04E", "#4EF16A", "#F14E4E", "#A04EF1",
              "#F1E24E", "#4EF1E2", "#F14EA0", "#7EF14E", "#F17E4E"]
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
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{svg_h}" '
        f'viewBox="0 0 {svg_w} {svg_h}">'
        f'<rect width="{svg_w}" height="{svg_h}" fill="#e8e8e8" stroke="#999" stroke-width="2"/>'
        f'{"".join(rects)}</svg>'
    )
