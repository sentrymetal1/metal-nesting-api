"""
1D Linear Nesting - Multi-Stock Best-Fit Decreasing
Algorithm:
  1. Sort all parts DESCENDING by length (longest first)
  2. For each part, find the shortest stock that fits it
  3. Try to pack it into an existing open bin of that stock size
  4. If no bin has room, open a new bin at the shortest viable stock size
  5. Pack as many additional parts as possible into each bin
  6. After all packing, downsize any bin that could use shorter stock

Stock matching: form_type + material_origin
"""


def nest_1d(parts, stock_options, kerf):
    # Group parts by form_type + material_origin
    groups = {}
    for part in parts:
        key = (part["form_type"], part["material_origin"])
        if key not in groups:
            groups[key] = {
                "cuts": [],
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
        cuts = group_data["cuts"]
        density = group_data["density"]

        # Match stock by form_type + material_origin
        matching_stock = [
            s for s in stock_options
            if s["form_type"].strip().lower() == form_type.strip().lower()
            and s["material_origin"].strip().lower() == mat_origin.strip().lower()
        ]

        if not matching_stock:
            stock_results.append({
                "error": f"No stock found for: {form_type} | {mat_origin}. Add to Nesting_Stock_Library.",
                "form_type": form_type,
                "material_origin": mat_origin
            })
            continue

        # Build stock lookup: length -> stock record, sorted ascending
        stock_by_length = {}
        for s in matching_stock:
            length = float(s["length_in"])
            if length not in stock_by_length:
                stock_by_length[length] = s
        available_lengths = sorted(stock_by_length.keys())  # shortest first

        # Sort parts longest first
        remaining_cuts = sorted(cuts, key=lambda c: c["length_in"], reverse=True)

        # Check if any stock can fit the longest part
        max_cut = max(c["length_in"] for c in remaining_cuts)
        max_stock = max(available_lengths)
        if max_stock < max_cut:
            stock_results.append({
                "error": f"No stock long enough for {form_type} | {mat_origin}. Largest part: {max_cut}\", longest stock: {max_stock}\".",
                "form_type": form_type,
                "material_origin": mat_origin
            })
            continue

        # --- Best-fit packing: for each part, find shortest stock that works ---
        bins = []

        for cut in remaining_cuts:
            cut_len = cut["length_in"]
            needed = cut_len + kerf

            # Try to fit into an existing bin (prefer bin with least remaining space that still fits)
            best_bin = None
            best_remaining = float("inf")
            for b in bins:
                if b["remaining"] >= needed and b["remaining"] - needed < best_remaining:
                    best_bin = b
                    best_remaining = b["remaining"] - needed

            if best_bin:
                best_bin["cuts"].append({
                    "part_mark":     cut["part_mark"],
                    "bom_line_id":   cut["bom_line_id"],
                    "material_type": cut["material_type"],
                    "spec_name":     cut["spec_name"],
                    "cut_length":    cut["length_in"],
                    "kerf":          kerf
                })
                best_bin["remaining"] -= needed
            else:
                # Open a new bin — find shortest stock that fits this part
                chosen_length = None
                for sl in available_lengths:
                    if sl >= needed:
                        chosen_length = sl
                        break

                if chosen_length is None:
                    stock_results.append({
                        "error": f"Part {cut['part_mark']} ({cut_len}\") too long for any stock in {form_type} | {mat_origin}.",
                        "form_type": form_type,
                        "material_origin": mat_origin
                    })
                    continue

                new_bin = {
                    "stock_length": chosen_length,
                    "chosen_stock": stock_by_length[chosen_length],
                    "remaining": chosen_length - needed,
                    "cuts": [{
                        "part_mark":     cut["part_mark"],
                        "bom_line_id":   cut["bom_line_id"],
                        "material_type": cut["material_type"],
                        "spec_name":     cut["spec_name"],
                        "cut_length":    cut["length_in"],
                        "kerf":          kerf
                    }]
                }
                bins.append(new_bin)

        # --- Optimization: try to consolidate bins ---
        bins = _optimize_bins(bins, kerf)

        # --- Final downsize: shrink each bin to shortest viable stock ---
        bins = _downsize_bins(bins, available_lengths, stock_by_length, kerf)

        # --- Build result records ---
        for b in bins:
            stock_length = b["stock_length"]
            chosen_stock = b["chosen_stock"]
            used_length = sum(c["cut_length"] + kerf for c in b["cuts"])
            remaining = stock_length - used_length
            waste_pct = round((remaining / stock_length) * 100, 2) if stock_length > 0 else 0
            weight = _calc_weight_1d(chosen_stock, used_length, density)

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
                        "quantity_on_this_stock":  0,
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
                "remnant_length_in": round(max(remaining, 0), 4),
                "waste_percentage":  waste_pct,
                "stock_weight_lbs":  round(weight, 3),
                "cuts":              list(cut_summary.values())
            })
            stock_sequence += 1

    return stock_results


def _optimize_bins(bins, kerf):
    """Try to move all cuts from one bin into others to eliminate bins."""
    improved = True
    while improved:
        improved = False
        bins.sort(key=lambda b: len(b["cuts"]))  # fewest cuts first = easiest to empty
        for i in range(len(bins)):
            if not bins[i]["cuts"]:
                continue
            # Try to move ALL cuts from bin[i] to other bins
            moves = []
            all_moved = True
            for cut in bins[i]["cuts"]:
                needed = cut["cut_length"] + kerf
                placed = False
                # Find best-fit target (least remaining space after placement)
                best_j = None
                best_rem = float("inf")
                for j in range(len(bins)):
                    if i == j:
                        continue
                    if bins[j]["remaining"] >= needed:
                        rem_after = bins[j]["remaining"] - needed
                        if rem_after < best_rem:
                            best_j = j
                            best_rem = rem_after
                if best_j is not None:
                    moves.append((cut, best_j))
                    placed = True
                if not placed:
                    all_moved = False
                    break

            if all_moved and moves:
                for cut, target_idx in moves:
                    bins[target_idx]["cuts"].append(cut)
                    bins[target_idx]["remaining"] -= (cut["cut_length"] + kerf)
                bins[i]["cuts"] = []
                improved = True

        bins = [b for b in bins if b["cuts"]]
    return bins


def _downsize_bins(bins, available_lengths, stock_by_length, kerf):
    """Shrink each bin to the shortest stock that fits all its cuts."""
    for b in bins:
        total_needed = sum(c["cut_length"] + kerf for c in b["cuts"])
        # Find shortest stock that fits
        for sl in available_lengths:  # already sorted ascending
            if sl >= total_needed:
                if sl < b["stock_length"]:
                    b["stock_length"] = sl
                    b["chosen_stock"] = stock_by_length[sl]
                    b["remaining"] = sl - total_needed
                elif sl == b["stock_length"]:
                    # Recalculate remaining in case it drifted
                    b["remaining"] = sl - total_needed
                break
    return bins


def _calc_weight_1d(stock, used_length_in, density):
    if not density or density == 0:
        return 0
    area_in2 = float(stock.get("area_in2", 0) or 0)
    thickness = float(stock.get("thickness_in", 0) or 0)
    width = float(stock.get("width_in", 0) or 0)
    if area_in2 > 0:
        return used_length_in * area_in2 * density
    if thickness > 0 and width > 0:
        return used_length_in * thickness * width * density
    return 0
