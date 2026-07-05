from mcp.server.fastmcp import FastMCP

mcp = FastMCP("EcoScan Tools")

@mcp.tool()
def get_local_recycling_rules(location: str, material: str) -> str:
    """Get localized recycling rules and bins for a material in a location.

    Args:
        location: City/region name
        material: Waste material type (e.g., plastic, battery, metal, organic)
    """
    loc = location.lower()
    mat = material.lower()
    # Mock database lookup
    if "seattle" in loc:
        if "plastic" in mat:
            return "Seattle: Recycle in blue bin. Bottles, jugs, and cups allowed. Must be clean and dry."
        elif "organic" in mat or "food" in mat or "compost" in mat:
            return "Seattle: Compost in green bin. All food scraps and yard waste are compostable."
        elif "battery" in mat or "hazardous" in mat or "paint" in mat:
            return "Seattle: DO NOT place in trash or recycling bins. Bring to South or North Household Hazardous Waste facility."
    elif "new york" in loc or "nyc" in loc:
        if "plastic" in mat:
            return "NYC: Recycle in blue bin. Hard plastics, bottles, and jugs only."
        elif "organic" in mat or "food" in mat:
            return "NYC: Place in brown compost bin. Required in residential buildings."
        elif "battery" in mat or "electronic" in mat:
            return "NYC: Illegal to dispose in trash. Take to retail collection sites or special waste drop-offs."
    
    # Generic fallback rules
    if "battery" in mat or "electronic" in mat or "hazardous" in mat:
        return f"Generic Warning: {material} contains hazardous components. Do not throw in household trash. Bring to a local hazardous waste center."
    return f"Generic recycling rule for {material} in {location}: Check local municipal guidelines. Rinse containers and remove non-recyclable parts."

@mcp.tool()
def identify_hazardous_materials(item_name: str) -> str:
    """Identify if a waste item contains hazardous material requiring special disposal.

    Args:
        item_name: The name or type of waste item
    """
    item = item_name.lower()
    hazardous_keywords = ["battery", "paint", "chemical", "oil", "pesticide", "fluorescent", "thermometer", "mercury", "aerosol", "medication", "solvent", "ammonia", "gasoline"]
    for kw in hazardous_keywords:
        if kw in item:
            return f"HAZARDOUS: {item_name} contains '{kw}'. It must NOT be placed in standard trash or recycling bins. Take it to a household hazardous waste facility."
    return f"SAFE/STANDARD: {item_name} does not match common hazardous waste profiles. Follow standard sorting rules."

@mcp.tool()
def lookup_dropoff_locations(location: str, item_category: str) -> str:
    """Look up recycling center drop-off locations for specialized or hazardous waste.

    Args:
        location: City or region name
        item_category: Type of waste (e.g., e-waste, hazard, compost)
    """
    loc = location.lower()
    cat = item_category.lower()
    if "seattle" in loc:
        if "hazard" in cat or "battery" in cat or "paint" in cat:
            return "Seattle: South Household Hazardous Waste Facility (8100 2nd Ave S) or North Facility (12500 Stone Ave N). Open Sun-Tue, free for residents."
        elif "e-waste" in cat or "electronic" in cat:
            return "Seattle E-Waste: Take to Seattle Goodwill or local E-Cycle Washington locations."
    elif "new york" in loc or "nyc" in loc:
        if "hazard" in cat or "battery" in cat:
            return "NYC: Special Waste Drop-Off Sites located in each borough (e.g., Greenpoint, Brooklyn). Open Saturdays."
    
    return f"Drop-off Locations: Search municipal waste services for '{item_category} recycling in {location}' or visit call2recycle.org for batteries."

if __name__ == "__main__":
    mcp.run()
