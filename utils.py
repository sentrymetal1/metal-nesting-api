"""
Utility functions: payload validation and summary builder
Stock matching: form_type + material_origin (from Specification.Material_Type_Origin)
"""

def validate_payload(payload):
    errors = []
    if not payload.get("project_id"):
        errors.append("Missing required field: project_id")
    parts_1d = payload.get("parts_1d", [])
    parts_2d = payload.get("parts_2d", [])
    if not parts_1d and not parts_2d:
        errors.append("At least one of parts_1d or parts_2d must be provided")
    for i, part in enumerate(parts_1d):
        for field in ["part_mark", "bom_line_id", "form_type", "material_origin", "length_in", "quantity"]:
            if field not in part:
                errors.append(f"parts_1d[{i}] missing field: {field}")
        if "length_in" in part and float(part["length_in"]) <= 0:
            errors.append(f"parts_1d[{i}] length_in must be > 0")
        if "quantity" in part and int(part["quantity"]) <= 0:
            errors.append(f"parts_1d[{i}] quantity must be > 0")
    for i, part in enumerate(parts_2d):
        for field in ["part_mark", "bom_line_id", "form_type", "material_origin", "length_in", "width_in", "thickness_in", "quantity"]:
            if field not in part:
                errors.append(f"parts_2d[{i}] missing field: {field}")
    for i, s in enumerate(payload.get("stock_1d", [])):
        for field in ["stock_id", "form_type", "material_origin", "length_in"]:
            if field not in s:
                errors.append(f"stock_1d[{i}] missing field: {field}")
    for i, s in enumerate(payload.get("stock_2d", [])):
        for field in ["stock_id", "form_type", "material_origin", "length_in", "width_in"]:
            if field not in s:
                errors.append(f"stock_2d[{i}] missing field: {field}")
    return errors

def build_summary(results_1d, results_2d):
    total_1d = len([r for r in results_1d if "error" not in r])
    total_2d = len([r for r in results_2d if "error" not in r])
    total_waste_1d = sum(r.get("remnant_length_in", 0) for r in results_1d if "error" not in r)
    total_waste_2d = sum(r.get("remnant_area_in2", 0) for r in results_2d if "error" not in r)
    avg_waste_1d = round(sum(r.get("waste_percentage", 0) for r in results_1d if "error" not in r) / total_1d, 2) if total_1d > 0 else 0
    avg_waste_2d = round(sum(r.get("waste_percentage", 0) for r in results_2d if "error" not in r) / total_2d, 2) if total_2d > 0 else 0
    total_weight = sum(r.get("stock_weight_lbs", 0) for r in results_1d + results_2d if "error" not in r)
    errors = [r["error"] for r in results_1d + results_2d if "error" in r]
    return {
        "total_stock_pieces":      total_1d + total_2d,
        "total_1d_stock_pieces":   total_1d,
        "total_2d_stock_pieces":   total_2d,
        "total_remnant_length_in": round(total_waste_1d, 4),
        "total_remnant_area_in2":  round(total_waste_2d, 4),
        "avg_waste_pct_1d":        avg_waste_1d,
        "avg_waste_pct_2d":        avg_waste_2d,
        "total_weight_lbs":        round(total_weight, 3),
        "errors":                  errors
    }
