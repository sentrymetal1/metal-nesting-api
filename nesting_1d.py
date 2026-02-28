"""
1D Linear Nesting - Multi-Stock Best-Fit Decreasing
Algorithm:
  1. Sort all available stock sizes DESCENDING (longest first)
  2. Sort all parts DESCENDING by length (longest first)
  3. For the longest stock, pack as many parts as possible (best-fit)
  4. Once a stock piece is full, open a new stock piece at the same length
  5. When no more parts fit the current stock length, step down to next shorter stock
  6. Each stock piece is filled to maximize usage (minimize waste)

Stock matching: form_type + material_origin
"""


def nest_1d(parts, stock_options, kerf):
    """
    parts: list of dicts with part_mark, bom_line_id, form_type, material_type,
           material_origin, spec_name, density, length_in, quantity
    stock_options: list of dicts with stock_id, stock_label, form_type,
                   material_origin, density, length_in, is_standard
    """

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

        # Sort parts longest first
        remaining_cuts = sorted(cuts, key=lambda c: c["length_in"], reverse=True)

        # Get unique stock lengths, sorted DESCENDING (longest first)
        stock_by_length = {}
        for s in matching_stock:
            length = float(s["length_in"])
            if length not in stock_by_length:
                stock_by_length[length] = s
        available_lengths = sorted(stock_by_length.keys(), reverse=True)

        if not available_lengths:
            stock_results.append({
                "error": f"No viable stock lengths for: {form_type} | {mat_origin}.",
                "form_type": form_type,
                "material_origin": mat_origin
            })
            continue

        # Check if longest stock can fit the longest part
        max_cut = max(c["length_in"] for c in remaining_cuts)
        max_stock = available_lengths[0]
        if max_stock < max_cut:
            stock_results.append({
                "error": f"No stock long enough for {form_type} | {mat_origin}. Largest part: {max_cut}\", longest stock: {max_stock}\". Add longer stock.",
                "form_type": form_type,
                "material_origin": mat_origin
            })
            continue

        # --- Multi-stock best-fit packing ---
        bins = []

        # Process each stock length from longest to shortest
        for stock_length in available_lengths:
            if not remaining_cuts:
                break

            chosen_stock = stock_by_length[stock_length]

            # Keep opening bins at this stock length as long as parts fit
            while remaining_cuts:
                # Find parts that fit this stock length
                fits_any = False
                for cut in remaining_cuts:
                    if cut["length_in"] + kerf <= stock_length:
                        fits_any = True
                        break

                if not fits_any:
                    break  # No remaining parts fit this stock length, try shorter

                # Open a new bin at this stock length
                current_bin = {
                    "stock_length": stock_length,
                    "chosen_stock": chosen_stock,
                    "remaining": stock_length,
                    "cuts": []
                }

                # Pack as many parts as possible into this bin (best-fit)
                # Try each remaining part, largest first
                still_remaining = []
                for cut in remaining_cuts:
                    needed = cut["length_in"] + kerf
                    if current_bin["remaining"] >= needed:
                        current_bin["cuts"].append({
                            "part_mark":     cut["part_mark"],
                            "bom_line_id":   cut["bom_line_id"],
                            "material_type": cut["material_type"],
                            "spec_name":     cut["spec_name"],
                            "cut_length":    cut["length_in"],
                            "kerf":          kerf
                        })
                        current_bin["remaining"] -= needed
                    else:
                        still_remaining.append(cut)

                if current_bin["cuts"]:
                    bins.append(current_bin)

                remaining_cuts = sorted(still_remaining, key=lambda c: c["length_in"], reverse=True)

        # Handle any parts that couldn't be placed (shouldn't happen if stock is adequate)
        if remaining_cuts:
            stock_results.append({
                "error": f"Could not place {len(remaining_cuts)} cuts for {form_type} | {mat_origin}. Parts may be longer than available stock.",
                "form_type": form_type,
                "material_origin": mat_origin
            })

        # --- Optimization pass: try to consolidate bins ---
        bins = _optimize_bins(bins, kerf)

        # --- Try to downsize bins to shorter stock where possible ---
        bins = _downsize_bins(bins, available_lengths, stock_by_length, kerf)

        # --- Build result records ---
        for b in bins:
            stock_length = b["stock_length"]
            chosen_stock = b["chosen_stock"]
            used_length = stock_length - b["remaining"]
            waste_pct = round((b["remaining"] / stock_length) * 100, 2)
            weight = _calc_weight_1d(chosen_stock, used_length, density)

            # Group cuts by part_mark + length
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
                "remnant_length_in": round(b["remaining"], 4),
                "waste_percentage":  waste_pct,
                "stock_weight_lbs":  round(weight, 3),
                "cuts":              list(cut_summary.values())
            })
            stock_sequence += 1

    return stock_results


def _optimize_bins(bins, kerf):
    """Try to move cuts from one bin to another to eliminate bins entirely."""
    improved = True
    while improved:
        improved = False
        # Sort bins by remaining space descending (most empty first — candidates for elimination)
        bins.sort(key=lambda b: b["remaining"], reverse=True)
        for i in range(len(bins) - 1, -1, -1):
            if not bins[i]["cuts"]:
                continue
            # Try to move ALL cuts from bin[i] to other bins
            all_moved = True
            moves = []
            for cut in bins[i]["cuts"]:
                placed = False
                for j in range(len(bins)):
                    if i == j:
                        continue
                    needed = cut["cut_length"] + kerf
                    if bins[j]["remaining"] >= needed:
                        moves.append((cut, j))
                        placed = True
                        break
                if not placed:
                    all_moved = False
                    break

            if all_moved and moves:
                # Execute all moves — eliminate bin[i]
                for cut, target_idx in moves:
                    bins[target_idx]["cuts"].append(cut)
                    bins[target_idx]["remaining"] -= (cut["cut_length"] + kerf)
                bins[i]["cuts"] = []
                improved = True

        bins = [b for b in bins if b["cuts"]]
    return bins


def _downsize_bins(bins, available_lengths, stock_by_length, kerf):
    """After packing, check if any bin can use a shorter stock size."""
    sorted_lengths = sorted(available_lengths)  # shortest first

    for b in bins:
        total_needed = sum(c["cut_length"] + kerf for c in b["cuts"])
        # Find the shortest stock that fits all cuts in this bin
        for length in sorted_lengths:
            if length >= total_needed:
                if length < b["stock_length"]:
                    b["stock_length"] = length
                    b["chosen_stock"] = stock_by_length[length]
                    b["remaining"] = length - total_needed
                break

    return bins


def _calc_weight_1d(stock, used_length_in, density):
    """Weight calculation."""
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
