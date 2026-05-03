"""
1D Linear Nesting - Multi-Stock Best-Fit Decreasing
Algorithm:
  1. Sort all parts DESCENDING by length (longest first)
  2. For each part, find the shortest stock that fits it
  3. Try to pack it into an existing open bin of that stock size
  4. If no bin has room, open a new bin at the shortest viable stock size
  5. Pack as many additional parts as possible into each bin
  6. After all packing, downsize any bin that could use shorter stock

Stock matching: form_type + material_origin, plus optional material_name
filter — when a stock entry has material_name set, it only matches parts
with the same material_name (normalized). Blank = generic.
"""


def _norm_mat(s):
    """Normalize material description for comparison: lowercase, strip all whitespace.
    'L5 x 3 x 1/4' and 'L5x3x1/4' both become 'l5x3x1/4'."""
    return "".join((s or "").lower().split())


def _stock_matches_material(stock_entry, cut_material_name):
    """A stock entry matches a cut if the stock has no material_name filter,
    or its (normalized) material_name equals the cut's (normalized) material_name."""
    sm = stock_entry.get("material_name", "")
    if not sm:
        return True
    return _norm_mat(sm) == _norm_mat(cut_material_name)


def _consumed_per_stock_id(bins):
    """Count how many bins currently use each stock_id."""
    counts = {}
    for b in bins:
        sid = b["chosen_stock"].get("stock_id")
        if sid is not None:
            counts[sid] = counts.get(sid, 0) + 1
    return counts


def _stock_at_cap(stock_entry, consumed):
    """True if this stock has a quantity cap and we've already used all of it."""
    qty = stock_entry.get("quantity")
    try:
        qty_int = int(qty) if qty not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        qty_int = None
    if qty_int is None or qty_int <= 0:
        return False  # no cap
    sid = stock_entry.get("stock_id")
    return consumed.get(sid, 0) >= qty_int


def _stock_is_tagged_for(stock_entry, cut_material_name):
    """True if this stock has a material_name filter that matches the cut.
    (Used to prefer tagged stock over generic when both are eligible.)"""
    sm = stock_entry.get("material_name", "")
    if not sm or not cut_material_name:
        return False
    return _norm_mat(sm) == _norm_mat(cut_material_name)


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
                "material_name": part.get("material_name", ""),
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

        def _new_cut_record(cut):
            return {
                "part_mark":     cut["part_mark"],
                "bom_line_id":   cut["bom_line_id"],
                "material_type": cut["material_type"],
                "material_name": cut.get("material_name", ""),
                "spec_name":     cut["spec_name"],
                "cut_length":    cut["length_in"],
                "kerf":          kerf
            }

        def _try_place(cut, needed, tagged_only):
            """Try to place a cut into an existing bin or open a new one.
            If tagged_only=True, only consider stock/bins specifically tagged for
            this cut's material_name (skip generic). Returns True if placed."""
            cut_mat = cut.get("material_name", "")

            # Existing bin fit
            best_bin = None
            best_remaining = float("inf")
            for b in bins:
                if not _stock_matches_material(b["chosen_stock"], cut_mat):
                    continue
                if tagged_only and not _stock_is_tagged_for(b["chosen_stock"], cut_mat):
                    continue
                if b["remaining"] >= needed and b["remaining"] - needed < best_remaining:
                    best_bin = b
                    best_remaining = b["remaining"] - needed

            if best_bin:
                best_bin["cuts"].append(_new_cut_record(cut))
                best_bin["remaining"] -= needed
                return True

            # Open a new bin
            consumed = _consumed_per_stock_id(bins)
            candidate_stock = [
                s for s in matching_stock
                if _stock_matches_material(s, cut_mat) and not _stock_at_cap(s, consumed)
                and (not tagged_only or _stock_is_tagged_for(s, cut_mat))
            ]
            chosen_stock = None
            for s in sorted(candidate_stock, key=lambda x: float(x["length_in"])):
                if float(s["length_in"]) >= needed:
                    chosen_stock = s
                    break
            if chosen_stock is None:
                return False

            chosen_length = float(chosen_stock["length_in"])
            bins.append({
                "stock_length": chosen_length,
                "chosen_stock": chosen_stock,
                "remaining":    chosen_length - needed,
                "cuts":         [_new_cut_record(cut)]
            })
            return True

        for cut in remaining_cuts:
            cut_len = cut["length_in"]
            cut_mat = cut.get("material_name", "")
            needed = cut_len + kerf

            # Tagged-first: if any stock is specifically tagged for this material,
            # try that path before falling back to generic stock. This ensures the
            # user's targeted custom stock actually gets used for matching parts.
            has_tagged = any(_stock_is_tagged_for(s, cut_mat) for s in matching_stock)
            placed = False
            if has_tagged:
                placed = _try_place(cut, needed, tagged_only=True)
            if not placed:
                placed = _try_place(cut, needed, tagged_only=False)

            if not placed:
                # Distinguish "no compatible stock" from "all compatible stock at qty cap"
                any_compatible = [
                    s for s in matching_stock
                    if _stock_matches_material(s, cut_mat) and float(s["length_in"]) >= needed
                ]
                if any_compatible:
                    err = f"Part {cut['part_mark']} ({cut_len}\") cannot be nested — all available stock at quantity cap"
                else:
                    err = f"Part {cut['part_mark']} ({cut_len}\") too long for any stock in {form_type} | {mat_origin}"
                if cut_mat:
                    err += f" matching material '{cut_mat}'"
                stock_results.append({
                    "error": err + ".",
                    "form_type": form_type,
                    "material_origin": mat_origin
                })
                continue

        # --- Optimization: try to consolidate bins ---
        bins = _optimize_bins(bins, kerf)

        # --- Final downsize: shrink each bin to shortest viable stock ---
        bins = _downsize_bins(bins, matching_stock, kerf)

        # --- Build result records ---
        for b in bins:
            stock_length = b["stock_length"]
            chosen_stock = b["chosen_stock"]
            used_length = sum(c["cut_length"] + kerf for c in b["cuts"])
            remaining = stock_length - used_length
            # Defense-in-depth: never display negative waste even if upstream packing drifts.
            waste_pct = round((max(remaining, 0) / stock_length) * 100, 2) if stock_length > 0 else 0
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
            # Project remaining capacity per target bin so multiple planned
            # moves to the same bin don't all see its original (pre-move) free space.
            projected = {j: bins[j]["remaining"] for j in range(len(bins)) if j != i}
            moves = []
            all_moved = True
            for cut in bins[i]["cuts"]:
                needed = cut["cut_length"] + kerf
                cut_mat = cut.get("material_name", "")
                # Find best-fit material-compatible target
                best_j = None
                best_rem = float("inf")
                for j, rem in projected.items():
                    if not _stock_matches_material(bins[j]["chosen_stock"], cut_mat):
                        continue
                    if rem >= needed:
                        rem_after = rem - needed
                        if rem_after < best_rem:
                            best_j = j
                            best_rem = rem_after
                if best_j is None:
                    all_moved = False
                    break
                moves.append((cut, best_j))
                projected[best_j] -= needed

            if all_moved and moves:
                for cut, target_idx in moves:
                    bins[target_idx]["cuts"].append(cut)
                    bins[target_idx]["remaining"] -= (cut["cut_length"] + kerf)
                bins[i]["cuts"] = []
                improved = True

        bins = [b for b in bins if b["cuts"]]
    return bins


def _downsize_bins(bins, matching_stock, kerf):
    """Shrink each bin to the shortest stock that fits all its cuts.
    Respects material_name compatibility AND quantity cap on candidate stock."""
    for b in bins:
        total_needed = sum(c["cut_length"] + kerf for c in b["cuts"])
        bin_mat = b["chosen_stock"].get("material_name", "")
        cur_sid = b["chosen_stock"].get("stock_id")

        # Treat this bin's current stock as freed when checking caps for candidates
        # (we'd be releasing one usage of cur_sid by downsizing).
        consumed = _consumed_per_stock_id(bins)
        if cur_sid is not None and consumed.get(cur_sid, 0) > 0:
            consumed = {**consumed, cur_sid: consumed[cur_sid] - 1}

        # Compatible candidates: same material constraint, not at cap
        candidates = sorted(
            [s for s in matching_stock
             if (s.get("material_name", "") or "") == (bin_mat or "")
             and not _stock_at_cap(s, consumed)],
            key=lambda x: float(x["length_in"])
        )
        for s in candidates:
            sl = float(s["length_in"])
            if sl >= total_needed:
                if sl < b["stock_length"]:
                    b["stock_length"] = sl
                    b["chosen_stock"] = s
                    b["remaining"] = sl - total_needed
                elif sl == b["stock_length"]:
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
