"""Lever — Bookable service catalog (Category → Service level).

Single source of truth for every bookable service, per the decision recorded
in docs/service-catalog-ux-audit.md §9: categories live in professions.py
(they carry code-coupled config), services live here as version-controlled
structured data served through GET /api/catalog. No service data may be
hard-coded in frontend screens.

Format: each service is a compact tuple
    (key, name_es, name_en, desc_es, desc_en, dur_min, dur_max, overrides)
where `overrides` is None or a dict overriding the category defaults:
    bt        booking_type: "instant" | "estimate"
    pt        pricing_type: "fixed" | "starting_at" | "hourly" | "per_m2"
              | "per_room" | "per_item" | "inspection_fee" | "estimate_required"
    risk      "low" | "medium" | "high"
    ver       verification: "none" | "enhanced"
    kw        extra search keywords (Ecuadorian Spanish synonyms)
    photos    bool — ask customer for photos
    materials bool — materials may be charged separately
    emergency bool — can be requested as an emergency
Durations are minutes. Spanish is Ecuadorian Spanish and is the primary text.

The loader at the bottom materializes full records; consumers use
ALL_SERVICES / SERVICES_BY_KEY / search_services().
"""

# ── Category defaults ────────────────────────────────────────────────────────
CATEGORY_DEFAULTS = {
    "home_cleaning":    {"bt": "instant",  "pt": "estimate_required", "risk": "low",    "ver": "none",     "photos": False, "materials": False},
    "plumbing":         {"bt": "estimate", "pt": "estimate_required", "risk": "medium", "ver": "none",     "photos": True,  "materials": True},
    "electrical":       {"bt": "estimate", "pt": "estimate_required", "risk": "medium", "ver": "enhanced", "photos": True,  "materials": True},
    "handyman":         {"bt": "instant",  "pt": "starting_at",       "risk": "low",    "ver": "none",     "photos": True,  "materials": True},
    "painting":         {"bt": "estimate", "pt": "estimate_required", "risk": "low",    "ver": "none",     "photos": True,  "materials": True},
    "construction":     {"bt": "estimate", "pt": "estimate_required", "risk": "high",   "ver": "enhanced", "photos": True,  "materials": True},
    "gardening":        {"bt": "instant",  "pt": "starting_at",       "risk": "low",    "ver": "none",     "photos": True,  "materials": False},
    "appliance_repair": {"bt": "estimate", "pt": "inspection_fee",    "risk": "medium", "ver": "none",     "photos": True,  "materials": True},
    "tech_support":     {"bt": "estimate", "pt": "starting_at",       "risk": "low",    "ver": "none",     "photos": True,  "materials": False},
    "beauty":           {"bt": "instant",  "pt": "fixed",             "risk": "low",    "ver": "none",     "photos": False, "materials": False},
    "automotive":       {"bt": "instant",  "pt": "starting_at",       "risk": "medium", "ver": "none",     "photos": True,  "materials": True},
    "moving":           {"bt": "instant",  "pt": "starting_at",       "risk": "low",    "ver": "none",     "photos": True,  "materials": False},
    "home_security":    {"bt": "estimate", "pt": "estimate_required", "risk": "medium", "ver": "enhanced", "photos": True,  "materials": True},
    "pets":             {"bt": "instant",  "pt": "fixed",             "risk": "low",    "ver": "none",     "photos": False, "materials": False},
    "events":           {"bt": "estimate", "pt": "estimate_required", "risk": "low",    "ver": "none",     "photos": False, "materials": False},
    "business_support": {"bt": "instant",  "pt": "hourly",            "risk": "low",    "ver": "none",     "photos": False, "materials": False},
}

# Category-level search synonyms (added to every service in the category)
CATEGORY_KEYWORDS = {
    "home_cleaning":    ["limpieza", "aseo", "empleada", "limpiar casa"],
    "plumbing":         ["plomero", "gasfitero", "tubería", "agua", "fuga"],
    "electrical":       ["electricista", "luz", "corriente", "electricidad"],
    "handyman":         ["maestro", "todero", "arreglos", "reparaciones"],
    "painting":         ["pintor", "pintura", "gypsum", "pared"],
    "construction":     ["albañil", "maestro de obra", "construcción", "obra"],
    "gardening":        ["jardinero", "jardín", "césped", "hierba", "monte"],
    "appliance_repair": ["técnico", "electrodoméstico", "reparación"],
    "tech_support":     ["computadora", "internet", "técnico de sistemas", "compu"],
    "beauty":           ["peluquería", "belleza", "estética", "a domicilio"],
    "automotive":       ["carro", "auto", "vehículo", "mecánico"],
    "moving":           ["mudanza", "flete", "camioneta", "cargador"],
    "home_security":    ["seguridad", "cámaras", "alarma", "vigilancia"],
    "pets":             ["mascota", "perro", "gato", "paseador"],
    "events":           ["evento", "fiesta", "matrimonio", "celebración"],
    "business_support": ["oficina", "negocio", "documentos", "trámites"],
}

# ── Per-category dynamic-form question sets (Phase 3 consumes these) ─────────
# Types: text | textarea | select | bool | photos | schedule
QUESTION_SETS = {
    "home_cleaning": [
        {"id": "property_type", "type": "select", "es": "Tipo de propiedad", "en": "Property type",
         "options": [{"v": "casa", "es": "Casa", "en": "House"}, {"v": "departamento", "es": "Departamento", "en": "Apartment"}, {"v": "oficina", "es": "Oficina", "en": "Office"}, {"v": "local", "es": "Local comercial", "en": "Commercial space"}], "required": True},
        {"id": "rooms", "type": "select", "es": "Número de habitaciones", "en": "Number of rooms",
         "options": [{"v": str(n), "es": str(n), "en": str(n)} for n in range(1, 7)] + [{"v": "7+", "es": "7 o más", "en": "7+"}], "required": True},
        {"id": "bathrooms", "type": "select", "es": "Número de baños", "en": "Number of bathrooms",
         "options": [{"v": str(n), "es": str(n), "en": str(n)} for n in range(1, 5)] + [{"v": "5+", "es": "5 o más", "en": "5+"}], "required": True},
        {"id": "supplies", "type": "select", "es": "¿Quién pone los productos de limpieza?", "en": "Who provides cleaning supplies?",
         "options": [{"v": "cliente", "es": "Yo los tengo", "en": "I have them"}, {"v": "profesional", "es": "El profesional los trae", "en": "The professional brings them"}], "required": True},
        {"id": "pets", "type": "bool", "es": "¿Hay mascotas en casa?", "en": "Pets at home?"},
        {"id": "notes", "type": "textarea", "es": "Instrucciones adicionales", "en": "Additional instructions"},
    ],
    "plumbing": [
        {"id": "problem", "type": "textarea", "es": "¿Cuál es el problema?", "en": "What is the problem?", "required": True},
        {"id": "location", "type": "select", "es": "¿Dónde está ubicado?", "en": "Where is it located?",
         "options": [{"v": "cocina", "es": "Cocina", "en": "Kitchen"}, {"v": "bano", "es": "Baño", "en": "Bathroom"}, {"v": "lavanderia", "es": "Lavandería", "en": "Laundry"}, {"v": "exterior", "es": "Exterior", "en": "Outdoors"}, {"v": "otro", "es": "Otro", "en": "Other"}], "required": True},
        {"id": "active_leak", "type": "bool", "es": "¿Está saliendo agua en este momento?", "en": "Is water actively leaking?"},
        {"id": "can_shutoff", "type": "bool", "es": "¿Puede cerrar la llave de paso?", "en": "Can the water supply be turned off?"},
        {"id": "since_when", "type": "text", "es": "¿Desde cuándo tiene el problema?", "en": "When did the problem begin?"},
    ],
    "electrical": [
        {"id": "problem", "type": "textarea", "es": "Describa el problema o trabajo", "en": "Describe the problem or task", "required": True},
        {"id": "scope", "type": "select", "es": "¿Afecta toda la casa o solo un área?", "en": "Whole home or one area?",
         "options": [{"v": "toda", "es": "Toda la casa", "en": "Whole home"}, {"v": "area", "es": "Solo un área", "en": "One area"}], "required": True},
        {"id": "breaker_trips", "type": "bool", "es": "¿Se dispara el breaker?", "en": "Does the breaker trip?"},
    ],
    "tech_support": [
        {"id": "device", "type": "select", "es": "Tipo de equipo", "en": "Device type",
         "options": [{"v": "laptop", "es": "Laptop", "en": "Laptop"}, {"v": "desktop", "es": "Computadora de escritorio", "en": "Desktop"}, {"v": "celular", "es": "Celular", "en": "Phone"}, {"v": "tablet", "es": "Tablet", "en": "Tablet"}, {"v": "impresora", "es": "Impresora", "en": "Printer"}, {"v": "red", "es": "Internet / Red", "en": "Internet / Network"}, {"v": "otro", "es": "Otro", "en": "Other"}], "required": True},
        {"id": "brand_model", "type": "text", "es": "Marca y modelo", "en": "Brand and model"},
        {"id": "problem", "type": "textarea", "es": "Describa el problema", "en": "Describe the problem", "required": True},
        {"id": "error_msg", "type": "text", "es": "Mensaje de error (si aparece)", "en": "Error message (if any)"},
        {"id": "mode", "type": "select", "es": "¿Prefiere soporte remoto o presencial?", "en": "Remote or in-person support?",
         "options": [{"v": "presencial", "es": "Presencial", "en": "In person"}, {"v": "remoto", "es": "Remoto", "en": "Remote"}, {"v": "cualquiera", "es": "Cualquiera", "en": "Either"}]},
        {"id": "has_internet", "type": "bool", "es": "¿Tiene internet disponible?", "en": "Internet available?"},
    ],
    "_default": [
        {"id": "description", "type": "textarea", "es": "Describa lo que necesita", "en": "Describe what you need", "required": True},
    ],
}

# ── Services ─────────────────────────────────────────────────────────────────
_S = {}

_S["home_cleaning"] = [
    ("standard_cleaning", "Limpieza estándar de casa", "Standard house cleaning", "Limpieza general de todos los ambientes de su casa.", "General cleaning of every room in your house.", 120, 300, {"pt": "per_room"}),
    ("apartment_cleaning", "Limpieza de departamento", "Apartment cleaning", "Limpieza completa de su departamento o suite.", "Full cleaning of your apartment or suite.", 90, 240, {"pt": "per_room"}),
    ("office_cleaning", "Limpieza de oficina", "Office cleaning", "Limpieza de oficinas y espacios de trabajo.", "Cleaning for offices and workspaces.", 90, 300, {"pt": "per_m2"}),
    ("weekly_cleaning", "Limpieza semanal", "Weekly cleaning", "Limpieza recurrente cada semana.", "Recurring cleaning every week.", 120, 240, {"pt": "per_room"}),
    ("biweekly_cleaning", "Limpieza quincenal", "Biweekly cleaning", "Limpieza recurrente cada dos semanas.", "Recurring cleaning every two weeks.", 120, 240, {"pt": "per_room"}),
    ("one_time_cleaning", "Limpieza por ocasión", "One-time cleaning", "Una sola visita de limpieza, sin compromiso.", "A single cleaning visit, no commitment.", 120, 300, {"pt": "per_room"}),
    ("deep_cleaning", "Limpieza profunda", "Deep cleaning", "Limpieza minuciosa incluyendo zonas difíciles.", "Thorough cleaning including hard-to-reach areas.", 180, 480, {"pt": "per_room", "kw": ["limpieza a fondo"]}),
    ("move_in_cleaning", "Limpieza de entrada (mudanza)", "Move-in cleaning", "Deje su nuevo hogar impecable antes de mudarse.", "Get your new home spotless before moving in.", 180, 420, None),
    ("move_out_cleaning", "Limpieza de salida (mudanza)", "Move-out cleaning", "Entregue la vivienda limpia al salir.", "Leave the property clean when moving out.", 180, 420, None),
    ("post_party_cleaning", "Limpieza después de fiesta", "Post-party cleaning", "Recuperamos su casa después del evento.", "We restore your home after the event.", 120, 300, {"emergency": True}),
    ("rental_cleaning", "Limpieza de alojamiento turístico", "Vacation-rental cleaning", "Limpieza entre huéspedes para Airbnb y similares.", "Turnover cleaning for Airbnb-style rentals.", 90, 240, {"kw": ["airbnb"]}),
    ("kitchen_deep_cleaning", "Limpieza profunda de cocina", "Kitchen deep cleaning", "Desengrase completo de cocina y mesones.", "Full degreasing of kitchen and counters.", 120, 240, None),
    ("bathroom_deep_cleaning", "Limpieza profunda de baños", "Bathroom deep cleaning", "Desinfección profunda de baños y azulejos.", "Deep disinfection of bathrooms and tile.", 60, 180, None),
    ("fridge_cleaning", "Limpieza de refrigeradora", "Refrigerator cleaning", "Limpieza interior y exterior de la refri.", "Inside-and-out fridge cleaning.", 45, 90, {"pt": "fixed", "kw": ["refri", "nevera"]}),
    ("oven_cleaning", "Limpieza de horno", "Oven cleaning", "Desengrase profundo del horno.", "Deep oven degreasing.", 45, 90, {"pt": "fixed"}),
    ("cabinet_cleaning", "Limpieza de armarios y muebles de cocina", "Cabinet cleaning", "Limpieza interna de armarios y alacenas.", "Inside cleaning of cabinets and cupboards.", 60, 120, None),
    ("window_cleaning", "Limpieza de ventanas", "Window cleaning", "Vidrios y marcos relucientes por dentro y fuera.", "Sparkling glass and frames inside and out.", 60, 240, {"pt": "per_item", "kw": ["vidrios"]}),
    ("glass_door_cleaning", "Limpieza de puertas de vidrio", "Glass-door cleaning", "Limpieza de mamparas y puertas de vidrio.", "Cleaning of glass doors and partitions.", 30, 90, {"pt": "per_item"}),
    ("balcony_cleaning", "Limpieza de balcón", "Balcony cleaning", "Balcones y terrazas pequeñas como nuevas.", "Balconies and small terraces like new.", 45, 120, None),
    ("patio_cleaning", "Limpieza de patio", "Patio cleaning", "Barrido y lavado de patios.", "Sweeping and washing of patios.", 60, 180, None),
    ("garage_cleaning", "Limpieza de garaje", "Garage cleaning", "Orden y limpieza de su garaje.", "Tidy-up and cleaning of your garage.", 60, 180, None),
    ("sofa_cleaning", "Limpieza de muebles y sofás", "Sofa cleaning", "Lavado y desmanchado de salas y sofás.", "Washing and stain removal for sofas.", 60, 180, {"pt": "per_item", "kw": ["lavado de muebles", "sala"]}),
    ("mattress_cleaning", "Limpieza de colchones", "Mattress cleaning", "Desinfección y desmanchado de colchones.", "Mattress disinfection and stain removal.", 45, 120, {"pt": "per_item", "kw": ["colchón"]}),
    ("carpet_cleaning", "Limpieza de alfombras", "Carpet cleaning", "Lavado profundo de alfombras y tapetes.", "Deep washing of carpets and rugs.", 60, 180, {"pt": "per_m2", "kw": ["alfombra"]}),
    ("curtain_cleaning", "Limpieza de cortinas", "Curtain cleaning", "Lavado de cortinas y persianas.", "Washing of curtains and blinds.", 60, 150, {"pt": "per_item"}),
    ("pressure_washing", "Lavado a presión", "Pressure washing", "Hidrolavado de pisos, paredes y fachadas.", "Pressure washing of floors, walls and façades.", 90, 300, {"pt": "per_m2", "kw": ["hidrolavado"]}),
    ("post_construction_cleaning", "Limpieza post construcción", "Post-construction cleaning", "Retiro de polvo y residuos después de una obra.", "Dust and debris removal after building work.", 240, 600, {"bt": "estimate", "photos": True}),
]

_S["plumbing"] = [
    ("faucet_leak_repair", "Reparación de llave que gotea", "Faucet leak repair", "Arreglo de grifos y llaves que gotean.", "Fixing dripping taps and faucets.", 30, 90, {"kw": ["llave de agua", "grifo gotea"]}),
    ("pipe_leak_repair", "Reparación de fuga en tubería", "Pipe leak repair", "Localizamos y reparamos la fuga de agua.", "We locate and repair the water leak.", 60, 240, {"emergency": True, "kw": ["tubería rota", "fuga de agua"]}),
    ("toilet_repair", "Reparación de inodoro", "Toilet repair", "Arreglo de inodoros que no descargan o gotean.", "Fixing toilets that run, leak or won't flush.", 45, 120, {"kw": ["baño dañado", "sanitario"]}),
    ("toilet_unclog", "Destape de inodoro", "Toilet unclogging", "Destapamos su inodoro rápidamente.", "We unclog your toilet fast.", 30, 90, {"emergency": True, "kw": ["baño tapado"]}),
    ("sink_unclog", "Destape de lavabo o fregadero", "Sink unclogging", "Destape de lavamanos y fregaderos.", "Unclogging of sinks and basins.", 30, 90, {"kw": ["lavabo tapado", "fregadero tapado"]}),
    ("shower_unclog", "Destape de ducha", "Shower unclogging", "Destape de duchas con mal drenaje.", "Unclogging slow-draining showers.", 30, 90, None),
    ("floor_drain_unclog", "Destape de sumidero", "Floor-drain unclogging", "Destape de rejillas y sumideros de piso.", "Unclogging floor drains and grates.", 30, 120, None),
    ("faucet_replacement", "Cambio de llave o grifo", "Faucet replacement", "Reemplazo de grifos dañados o viejos.", "Replacing damaged or old faucets.", 45, 120, None),
    ("kitchen_faucet_install", "Instalación de grifo de cocina", "Kitchen-faucet installation", "Instalación de grifería de cocina nueva.", "Installation of new kitchen faucets.", 45, 120, None),
    ("bathroom_faucet_install", "Instalación de grifo de baño", "Bathroom-faucet installation", "Instalación de grifería de baño nueva.", "Installation of new bathroom faucets.", 45, 120, None),
    ("sink_install", "Instalación de lavabo", "Sink installation", "Instalación de lavamanos y fregaderos.", "Installation of sinks and basins.", 60, 180, None),
    ("toilet_install", "Instalación de inodoro", "Toilet installation", "Instalación o cambio de inodoro.", "Installation or replacement of a toilet.", 90, 180, None),
    ("shower_install", "Instalación de ducha", "Shower installation", "Instalación de duchas y mezcladoras.", "Installation of showers and mixers.", 120, 300, None),
    ("showerhead_replacement", "Cambio de regadera de ducha", "Showerhead replacement", "Cambio de la regadera o teleducha.", "Replacing the showerhead.", 20, 45, {"bt": "instant", "pt": "fixed"}),
    ("water_tank_repair", "Reparación de cisterna o tanque", "Water-tank repair", "Reparación de cisternas y tanques elevados.", "Repair of cisterns and rooftop tanks.", 90, 300, None),
    ("water_tank_cleaning", "Limpieza de cisterna", "Water-tank cleaning", "Lavado y desinfección de cisternas.", "Washing and disinfection of water tanks.", 120, 300, {"bt": "instant", "pt": "starting_at"}),
    ("water_pump_install", "Instalación de bomba de agua", "Water-pump installation", "Instalación de bombas y sistemas de presión.", "Installation of pumps and pressure systems.", 120, 300, None),
    ("water_pump_repair", "Reparación de bomba de agua", "Water-pump repair", "Diagnóstico y arreglo de bombas de agua.", "Diagnosis and repair of water pumps.", 60, 240, None),
    ("water_heater_install", "Instalación de calefón o calentador", "Water-heater installation", "Instalación de calefones a gas o eléctricos.", "Installation of gas or electric water heaters.", 120, 300, {"risk": "high", "kw": ["calefón"]}),
    ("water_heater_repair", "Reparación de calefón", "Water-heater repair", "Reparación de calefones y termostatos.", "Repair of water heaters and thermostats.", 60, 180, {"risk": "high", "kw": ["no hay agua caliente"]}),
    ("leak_detection", "Detección de fugas de agua", "Water-leak detection", "Encontramos fugas ocultas en paredes y pisos.", "We find hidden leaks in walls and floors.", 60, 180, {"pt": "inspection_fee"}),
    ("low_pressure_diagnosis", "Diagnóstico de baja presión de agua", "Low-water-pressure diagnosis", "Averiguamos por qué llega poca agua.", "We find out why water pressure is low.", 45, 120, {"pt": "inspection_fee", "kw": ["poca agua"]}),
    ("pipe_replacement", "Cambio de tuberías", "Pipe replacement", "Reemplazo de tramos de tubería dañada.", "Replacing damaged pipe sections.", 120, 480, None),
    ("washer_connection", "Conexión de lavadora", "Washing-machine water connection", "Instalamos las tomas de agua de su lavadora.", "We hook up your washing machine's water lines.", 45, 120, {"bt": "instant", "pt": "fixed"}),
    ("dishwasher_connection", "Conexión de lavavajillas", "Dishwasher water connection", "Conexión de agua y desagüe del lavavajillas.", "Water and drain hookup for dishwashers.", 45, 120, {"bt": "instant", "pt": "fixed"}),
    ("exterior_drain_repair", "Reparación de desagüe exterior", "Exterior drain repair", "Arreglo de canaletas y desagües externos.", "Repair of outdoor drains and gutters.", 90, 300, None),
    ("plumbing_inspection", "Inspección de plomería", "Plumbing inspection", "Revisión general del sistema de agua.", "General check of your water system.", 60, 120, {"pt": "inspection_fee"}),
]

_S["electrical"] = [
    ("outlet_replacement", "Cambio de tomacorriente", "Outlet replacement", "Cambio de tomacorrientes dañados o flojos.", "Replacing damaged or loose outlets.", 30, 60, {"risk": "medium", "kw": ["enchufe"]}),
    ("switch_replacement", "Cambio de interruptor", "Switch replacement", "Cambio de interruptores de luz.", "Replacing light switches.", 30, 60, {"risk": "medium"}),
    ("light_fixture_install", "Instalación de lámparas", "Light-fixture installation", "Instalación de lámparas y apliques.", "Installing lamps and fixtures.", 30, 90, {"risk": "medium", "kw": ["foco", "luminaria"]}),
    ("ceiling_light_install", "Instalación de luz de techo", "Ceiling-light installation", "Instalación de plafones y luces de techo.", "Installing ceiling lights.", 45, 90, {"risk": "medium"}),
    ("ceiling_fan_install", "Instalación de ventilador de techo", "Ceiling-fan installation", "Montaje y conexión de ventiladores de techo.", "Mounting and wiring ceiling fans.", 60, 120, {"risk": "medium"}),
    ("fault_diagnosis", "Diagnóstico de falla eléctrica", "Electrical fault diagnosis", "Encontramos por qué no hay luz o falla la corriente.", "We find why power fails or lights go out.", 60, 180, {"pt": "inspection_fee", "emergency": True, "kw": ["no hay luz", "se fue la luz"]}),
    ("breaker_replacement", "Cambio de breaker", "Circuit-breaker replacement", "Cambio de breakers disparados o dañados.", "Replacing tripped or faulty breakers.", 30, 90, {"risk": "high"}),
    ("panel_inspection", "Revisión de tablero eléctrico", "Electrical-panel inspection", "Inspección de seguridad del tablero.", "Safety inspection of the electrical panel.", 60, 120, {"pt": "inspection_fee", "risk": "high"}),
    ("new_outlet_install", "Instalación de tomacorriente adicional", "Additional outlet installation", "Puntos de corriente nuevos donde los necesita.", "New power points where you need them.", 60, 150, {"risk": "high"}),
    ("outdoor_light_install", "Instalación de luces exteriores", "Outdoor-light installation", "Iluminación de patios, jardines y fachadas.", "Lighting for patios, gardens and façades.", 60, 180, {"risk": "medium"}),
    ("motion_sensor_install", "Instalación de sensor de movimiento", "Motion-sensor installation", "Sensores de movimiento para luces.", "Motion sensors for lighting.", 45, 90, {"risk": "medium"}),
    ("doorbell_install", "Instalación de timbre", "Doorbell installation", "Instalación o cambio de timbre.", "Installing or replacing a doorbell.", 30, 90, {"risk": "low", "ver": "none"}),
    ("wiring_repair", "Reparación de cableado", "Electrical wiring repair", "Arreglo de cables dañados o empalmes malos.", "Fixing damaged wiring and bad splices.", 90, 300, {"risk": "high"}),
    ("voltage_diagnosis", "Diagnóstico de problemas de voltaje", "Voltage problem diagnosis", "Solución a variaciones y bajones de voltaje.", "Solving voltage drops and fluctuations.", 60, 150, {"pt": "inspection_fee", "risk": "high"}),
    ("short_circuit_diagnosis", "Diagnóstico de cortocircuito", "Short-circuit diagnosis", "Localización y arreglo de cortocircuitos.", "Locating and fixing short circuits.", 60, 240, {"risk": "high", "emergency": True, "kw": ["corto", "chispas"]}),
    ("appliance_connection", "Conexión eléctrica de electrodomésticos", "Appliance electrical connection", "Conexión segura de cocinas, secadoras y más.", "Safe hookup of stoves, dryers and more.", 45, 120, {"risk": "high", "kw": ["cocina de inducción"]}),
    ("generator_connection", "Conexión de generador", "Generator connection", "Instalación de generadores de respaldo.", "Backup generator installation.", 120, 360, {"risk": "high"}),
    ("surge_protector_install", "Instalación de protector de picos", "Surge-protector installation", "Protección contra subidas de voltaje.", "Protection against voltage surges.", 45, 90, {"risk": "medium"}),
    ("electrical_safety_inspection", "Inspección de seguridad eléctrica", "Electrical safety inspection", "Revisión completa de la instalación.", "Full inspection of your wiring.", 90, 180, {"pt": "inspection_fee", "risk": "medium"}),
]

_S["handyman"] = [
    ("furniture_assembly", "Ensamblaje de muebles", "Furniture assembly", "Armamos sus muebles nuevos.", "We assemble your new furniture.", 45, 180, {"pt": "per_item", "kw": ["armar muebles"]}),
    ("shelf_install", "Instalación de repisas", "Shelf installation", "Colocación firme de repisas y estanterías.", "Secure mounting of shelves.", 30, 90, {"pt": "per_item"}),
    ("curtain_rod_install", "Instalación de cortineros", "Curtain-rod installation", "Instalación de cortineros y rieles.", "Installing curtain rods and rails.", 30, 90, {"pt": "per_item", "kw": ["cortinas"]}),
    ("tv_mounting", "Instalación de TV en pared", "Television wall mounting", "Montaje seguro de su televisor.", "Safe wall-mounting of your TV.", 45, 120, {"pt": "fixed", "kw": ["colgar tele", "soporte tv"]}),
    ("mirror_install", "Instalación de espejos", "Mirror installation", "Colocación de espejos con seguridad.", "Safe mirror installation.", 30, 90, {"pt": "per_item"}),
    ("picture_hanging", "Colgado de cuadros", "Picture hanging", "Colgamos cuadros y decoración.", "We hang pictures and décor.", 20, 60, {"pt": "per_item"}),
    ("door_handle_replacement", "Cambio de manijas de puerta", "Door-handle replacement", "Cambio de manijas y pomos.", "Replacing handles and knobs.", 20, 60, {"pt": "per_item"}),
    ("lock_replacement", "Cambio de cerraduras", "Lock replacement", "Cambio de cerraduras y chapas.", "Replacing locks.", 30, 90, {"pt": "per_item", "emergency": True, "kw": ["cerrajero", "me quedé fuera", "chapa"]}),
    ("cabinet_hardware_install", "Instalación de herrajes de muebles", "Cabinet-hardware installation", "Cambio de tiradores y bisagras.", "Replacing pulls and hinges.", 30, 90, None),
    ("minor_door_repair", "Reparación menor de puertas", "Minor door repair", "Ajuste de puertas que rozan o no cierran.", "Fixing doors that stick or won't close.", 45, 120, None),
    ("minor_window_repair", "Reparación menor de ventanas", "Minor window repair", "Arreglo de ventanas y correderas.", "Fixing windows and sliders.", 45, 120, None),
    ("small_wall_repair", "Resane de pared pequeño", "Small wall repair", "Resane de huecos y fisuras pequeñas.", "Patching small holes and cracks.", 45, 120, None),
    ("caulking_sealing", "Sellado con silicona", "Caulking and sealing", "Sellado de tinas, mesones y ventanas.", "Sealing tubs, counters and windows.", 30, 120, None),
    ("bathroom_accessory_install", "Instalación de accesorios de baño", "Bathroom-accessory installation", "Toalleros, espejos y repisas de baño.", "Towel bars, mirrors and bath shelves.", 30, 90, {"pt": "per_item"}),
    ("kitchen_accessory_install", "Instalación de accesorios de cocina", "Kitchen-accessory installation", "Organizadores y accesorios de cocina.", "Kitchen organizers and accessories.", 30, 90, {"pt": "per_item"}),
    ("child_safety_install", "Instalación de seguridad para niños", "Child-safety fixture installation", "Rejas, seguros y anclajes de muebles.", "Gates, latches and furniture anchors.", 45, 120, None),
    ("maintenance_visit", "Visita de mantenimiento general", "General home-maintenance visit", "Una visita para resolver varias tareas pequeñas.", "One visit to knock out several small tasks.", 120, 300, {"pt": "hourly"}),
]

_S["painting"] = [
    ("interior_painting", "Pintura de interiores", "Interior room painting", "Pintamos habitaciones y espacios interiores.", "We paint rooms and interior spaces.", 240, 960, {"pt": "per_m2", "kw": ["pintar cuarto"]}),
    ("exterior_painting", "Pintura de exteriores", "Exterior painting", "Pintura de fachadas y exteriores.", "Painting façades and exteriors.", 480, 1920, {"pt": "per_m2"}),
    ("ceiling_painting", "Pintura de techos", "Ceiling painting", "Pintura de techos y tumbados.", "Painting ceilings.", 120, 480, {"pt": "per_m2", "kw": ["tumbado"]}),
    ("door_painting", "Pintura de puertas", "Door painting", "Lacado y pintura de puertas.", "Painting and lacquering doors.", 60, 180, {"pt": "per_item"}),
    ("fence_painting", "Pintura de cerramientos", "Fence painting", "Pintura de rejas y cerramientos.", "Painting fences and railings.", 120, 480, None),
    ("wall_preparation", "Preparación de paredes", "Wall preparation", "Preparamos la superficie antes de pintar.", "Surface prep before painting.", 120, 480, None),
    ("wall_sanding", "Lijado de paredes", "Wall sanding", "Lijado fino para un acabado parejo.", "Fine sanding for an even finish.", 60, 240, None),
    ("crack_repair", "Reparación de fisuras", "Crack repair", "Sellado de fisuras antes del acabado.", "Sealing cracks before finishing.", 60, 240, None),
    ("hole_repair", "Reparación de huecos", "Hole repair", "Resane de huecos en paredes.", "Patching holes in walls.", 45, 120, None),
    ("drywall_install", "Instalación de gypsum", "Drywall installation", "Paredes y cielos rasos de gypsum.", "Drywall walls and ceilings.", 240, 960, {"kw": ["gypsum", "cielo raso"]}),
    ("drywall_patching", "Parchado de gypsum", "Drywall patching", "Reparación de golpes y huecos en gypsum.", "Repairing dents and holes in drywall.", 60, 180, None),
    ("drywall_finishing", "Acabado de gypsum", "Drywall finishing", "Masillado y acabado fino de gypsum.", "Taping and finishing drywall.", 120, 480, None),
    ("joint_compound", "Empaste de paredes", "Joint-compound application", "Empastado para paredes lisas.", "Skim coating for smooth walls.", 120, 480, {"pt": "per_m2", "kw": ["empaste"]}),
    ("texture_application", "Aplicación de textura", "Texture application", "Texturizados decorativos en paredes.", "Decorative wall textures.", 120, 480, None),
    ("texture_repair", "Reparación de textura", "Texture repair", "Igualamos la textura existente.", "Matching your existing texture.", 60, 240, None),
    ("moisture_drywall_replacement", "Cambio de gypsum dañado por humedad", "Moisture-damaged drywall replacement", "Reemplazo de planchas dañadas por agua.", "Replacing water-damaged panels.", 120, 480, None),
    ("baseboard_painting", "Pintura de barrederas", "Baseboard painting", "Pintura de barrederas y molduras.", "Painting baseboards and trim.", 60, 240, {"kw": ["barredera"]}),
    ("commercial_painting", "Pintura comercial pequeña", "Small commercial painting", "Pintura de locales y oficinas pequeñas.", "Painting small shops and offices.", 480, 1920, None),
    ("color_consultation", "Asesoría de colores", "Color consultation", "Le ayudamos a elegir la paleta ideal.", "We help you pick the right palette.", 45, 90, {"bt": "instant", "pt": "fixed", "photos": False, "materials": False}),
]

_S["construction"] = [
    ("brick_laying", "Mampostería (ladrillo/bloque)", "Brick laying", "Levantamos paredes de ladrillo o bloque.", "Building brick or block walls.", 480, 2400, None),
    ("concrete_repair", "Reparación de hormigón", "Concrete repair", "Reparación de losas y elementos de hormigón.", "Repairing slabs and concrete elements.", 240, 960, None),
    ("small_concrete_slab", "Fundición de losa pequeña", "Small concrete slab", "Contrapisos y losas pequeñas.", "Small slabs and subfloors.", 480, 1440, None),
    ("wall_construction", "Construcción de paredes", "Wall construction", "Paredes nuevas interiores o exteriores.", "New interior or exterior walls.", 480, 1920, None),
    ("wall_repair", "Reparación de paredes", "Wall repair", "Arreglo de paredes agrietadas o dañadas.", "Fixing cracked or damaged walls.", 240, 960, None),
    ("tile_install", "Instalación de cerámica o porcelanato", "Tile installation", "Colocación de cerámica, porcelanato y baldosa.", "Laying ceramic and porcelain tile.", 480, 1920, {"pt": "per_m2", "kw": ["cerámica", "porcelanato", "baldosa"]}),
    ("tile_repair", "Reparación de cerámica", "Tile repair", "Cambio de piezas rotas o flojas.", "Replacing broken or loose tiles.", 120, 480, None),
    ("floor_install", "Instalación de pisos", "Floor installation", "Pisos flotantes, vinílicos y más.", "Laminate, vinyl and other flooring.", 480, 1440, {"pt": "per_m2", "kw": ["piso flotante"]}),
    ("floor_repair", "Reparación de pisos", "Floor repair", "Arreglo de pisos hundidos o dañados.", "Fixing sunken or damaged floors.", 240, 960, None),
    ("cement_finishing", "Acabados de cemento", "Cement finishing", "Alisado y acabados de cemento.", "Cement smoothing and finishes.", 240, 960, None),
    ("demolition_assistance", "Ayuda en demolición", "Demolition assistance", "Demolición controlada de paredes y pisos.", "Controlled demolition of walls and floors.", 240, 1440, {"risk": "high"}),
    ("debris_removal", "Retiro de escombros", "Debris removal", "Sacamos y transportamos escombros.", "We haul away construction debris.", 120, 480, {"bt": "instant", "pt": "starting_at", "kw": ["desalojo"]}),
    ("small_remodeling", "Remodelación pequeña", "Small remodeling project", "Remodelaciones puntuales de espacios.", "Targeted space remodels.", 960, 4800, None),
    ("bathroom_remodeling", "Remodelación de baño", "Bathroom remodeling", "Renovación completa de baños.", "Full bathroom renovations.", 1440, 7200, None),
    ("kitchen_remodeling", "Remodelación de cocina", "Kitchen remodeling", "Renovación completa de cocinas.", "Full kitchen renovations.", 1440, 9600, None),
    ("fence_construction", "Construcción de cerramientos", "Fence construction", "Cerramientos de bloque, malla o reja.", "Block, mesh or rail fencing.", 480, 2400, None),
    ("gate_install", "Instalación de puertas y portones", "Gate installation", "Instalación de portones y puertas metálicas.", "Installing gates and metal doors.", 240, 960, None),
    ("roofing_repair", "Reparación de techos y cubiertas", "Roofing repair", "Arreglo de goteras y cubiertas.", "Fixing leaks and roofing.", 240, 960, {"risk": "high", "emergency": True, "kw": ["gotera", "techo"]}),
    ("waterproofing", "Impermeabilización", "Waterproofing", "Impermeabilización de losas y terrazas.", "Waterproofing slabs and terraces.", 480, 1440, {"kw": ["humedad", "filtración"]}),
    ("structural_inspection", "Solicitud de inspección estructural", "Structural inspection request", "Evaluación profesional de la estructura.", "Professional structural assessment.", 90, 240, {"pt": "inspection_fee", "risk": "high"}),
]

_S["gardening"] = [
    ("grass_cutting", "Corte de césped", "Grass cutting", "Corte y orillado de césped.", "Mowing and edging your lawn.", 60, 240, {"kw": ["cortar hierba", "podar césped"]}),
    ("yard_cleanup", "Limpieza de patios y terrenos", "Yard cleanup", "Limpieza general de patios y terrenos.", "General yard and lot cleanup.", 120, 480, {"kw": ["desbrozar", "limpiar terreno"]}),
    ("weed_removal", "Retiro de maleza", "Weed removal", "Eliminamos maleza y monte.", "We remove weeds and overgrowth.", 60, 300, {"kw": ["monte", "maleza"]}),
    ("plant_trimming", "Poda de plantas", "Plant trimming", "Poda y formado de plantas.", "Trimming and shaping plants.", 60, 240, None),
    ("hedge_trimming", "Poda de setos", "Hedge trimming", "Setos parejos y bien formados.", "Neat, even hedges.", 60, 240, {"kw": ["cerca viva"]}),
    ("tree_pruning", "Poda de árboles", "Tree pruning", "Poda segura de ramas y copas.", "Safe pruning of branches and crowns.", 120, 480, {"risk": "medium", "bt": "estimate"}),
    ("small_tree_removal", "Tala de árbol pequeño", "Small-tree removal", "Retiro de árboles pequeños con seguridad.", "Safe removal of small trees.", 180, 480, {"risk": "medium", "bt": "estimate"}),
    ("garden_maintenance", "Mantenimiento de jardín", "Garden maintenance", "Cuidado integral y periódico del jardín.", "Complete, recurring garden care.", 120, 300, None),
    ("flower_planting", "Siembra de flores", "Flower planting", "Plantamos flores de temporada.", "Planting seasonal flowers.", 60, 240, None),
    ("plant_install", "Instalación de plantas", "Plant installation", "Plantación de arbustos y plantas nuevas.", "Planting new shrubs and plants.", 60, 240, None),
    ("soil_preparation", "Preparación de tierra", "Soil preparation", "Preparamos el suelo para sembrar.", "Preparing soil for planting.", 120, 360, None),
    ("fertilizing", "Fertilización", "Fertilizing", "Abonado y nutrición del jardín.", "Feeding and fertilizing the garden.", 45, 120, None),
    ("irrigation_install", "Instalación de riego", "Irrigation-system installation", "Sistemas de riego automáticos.", "Automatic irrigation systems.", 240, 960, {"bt": "estimate"}),
    ("irrigation_repair", "Reparación de riego", "Irrigation repair", "Arreglo de aspersores y líneas de riego.", "Fixing sprinklers and irrigation lines.", 60, 240, None),
    ("outdoor_pest_cleanup", "Control de plagas de jardín", "Outdoor pest cleanup", "Tratamiento de plagas en áreas verdes.", "Treating pests in green areas.", 60, 180, None),
    ("leaf_removal", "Recolección de hojas", "Leaf removal", "Recogemos y retiramos hojas secas.", "Raking and removing fallen leaves.", 60, 180, None),
    ("patio_cleanup", "Limpieza de áreas exteriores", "Patio cleanup", "Limpieza de terrazas y áreas verdes.", "Cleaning terraces and green areas.", 60, 240, None),
    ("landscaping_design", "Diseño de jardines", "Landscaping design", "Diseño y planificación de su jardín.", "Design and planning of your garden.", 90, 240, {"bt": "estimate"}),
    ("garden_restoration", "Recuperación de jardines", "Garden restoration", "Revivimos jardines descuidados.", "Bringing neglected gardens back to life.", 240, 960, {"bt": "estimate"}),
    ("green_waste_removal", "Retiro de desechos de jardín", "Green-waste removal", "Sacamos ramas, hojas y desechos verdes.", "We haul away branches and green waste.", 60, 240, None),
]

_S["appliance_repair"] = [
    ("fridge_diagnosis", "Diagnóstico de refrigeradora", "Refrigerator diagnosis", "Averiguamos qué tiene su refri.", "We find out what's wrong with your fridge.", 45, 90, {"kw": ["refri no enfría", "nevera"]}),
    ("fridge_repair", "Reparación de refrigeradora", "Refrigerator repair", "Reparación de refrigeradoras a domicilio.", "In-home refrigerator repair.", 60, 240, None),
    ("washer_diagnosis", "Diagnóstico de lavadora", "Washing-machine diagnosis", "Diagnóstico de fallas de lavadora.", "Washing-machine fault diagnosis.", 45, 90, {"kw": ["lavadora no prende", "lavadora dañada"]}),
    ("washer_repair", "Reparación de lavadora", "Washing-machine repair", "Reparación de lavadoras todas las marcas.", "Washer repair, all brands.", 60, 240, None),
    ("dryer_repair", "Reparación de secadora", "Dryer repair", "Reparación de secadoras de ropa.", "Clothes-dryer repair.", 60, 240, None),
    ("stove_repair", "Reparación de cocina", "Stove repair", "Arreglo de cocinas a gas e inducción.", "Fixing gas and induction stoves.", 60, 240, {"risk": "high", "kw": ["cocineta"]}),
    ("oven_repair", "Reparación de horno", "Oven repair", "Reparación de hornos eléctricos y a gas.", "Electric and gas oven repair.", 60, 240, {"risk": "high"}),
    ("microwave_repair", "Reparación de microondas", "Microwave repair", "Reparación de hornos microondas.", "Microwave oven repair.", 45, 120, None),
    ("dishwasher_repair", "Reparación de lavavajillas", "Dishwasher repair", "Reparación de lavavajillas.", "Dishwasher repair.", 60, 240, None),
    ("water_dispenser_repair", "Reparación de dispensador de agua", "Water-dispenser repair", "Arreglo de dispensadores fríos/calientes.", "Fixing hot/cold water dispensers.", 45, 120, None),
    ("ac_diagnosis", "Diagnóstico de aire acondicionado", "Air-conditioner diagnosis", "Diagnóstico de fallas del A/C.", "A/C fault diagnosis.", 45, 90, {"kw": ["aire no enfría", "split"]}),
    ("ac_maintenance", "Mantenimiento de aire acondicionado", "Air-conditioner maintenance", "Limpieza y mantenimiento preventivo del A/C.", "A/C cleaning and preventive maintenance.", 60, 150, {"bt": "instant", "pt": "fixed"}),
    ("ac_repair", "Reparación de aire acondicionado", "Air-conditioner repair", "Reparación y recarga de aires acondicionados.", "A/C repair and recharge.", 60, 240, None),
    ("ac_install", "Instalación de aire acondicionado", "Air-conditioner installation", "Instalación de splits y ventanas.", "Installing split and window units.", 120, 360, {"risk": "high"}),
    ("fan_repair", "Reparación de ventiladores", "Fan repair", "Arreglo de ventiladores de pie y techo.", "Fixing stand and ceiling fans.", 45, 120, None),
    ("small_appliance_repair", "Reparación de electrodomésticos pequeños", "Small-appliance repair", "Licuadoras, planchas, cafeteras y más.", "Blenders, irons, coffee makers and more.", 30, 90, None),
    ("preventive_maintenance", "Visita de mantenimiento preventivo", "Preventive maintenance visit", "Revisión general de sus electrodomésticos.", "General checkup of your appliances.", 60, 150, {"bt": "instant", "pt": "fixed"}),
]

_S["tech_support"] = [
    ("computer_diagnosis", "Diagnóstico de computadora", "Computer diagnosis", "Averiguamos qué le pasa a su equipo.", "We find out what's wrong with your computer.", 45, 90, {"kw": ["computadora lenta", "pc dañada"]}),
    ("laptop_repair", "Reparación de laptop", "Laptop repair", "Reparación de laptops todas las marcas.", "Laptop repair, all brands.", 60, 240, None),
    ("desktop_repair", "Reparación de computadora de escritorio", "Desktop repair", "Reparación de PCs de escritorio.", "Desktop PC repair.", 60, 240, None),
    ("os_install", "Instalación de sistema operativo", "Operating-system installation", "Formateo e instalación de Windows u otros.", "Formatting and installing Windows or others.", 90, 180, {"pt": "fixed", "kw": ["formatear"]}),
    ("virus_removal", "Eliminación de virus", "Virus and malware removal", "Limpiamos virus y programas maliciosos.", "We remove viruses and malware.", 60, 180, {"kw": ["virus", "hackeado"]}),
    ("computer_cleanup", "Limpieza de computadora", "Computer cleanup", "Limpieza física y de software.", "Physical and software cleanup.", 45, 120, {"bt": "instant", "pt": "fixed"}),
    ("performance_optimization", "Optimización de rendimiento", "Computer performance optimization", "Su equipo más rápido y estable.", "A faster, more stable machine.", 60, 150, {"bt": "instant", "pt": "fixed", "kw": ["computadora lenta"]}),
    ("data_backup", "Respaldo de información", "Data backup", "Respaldamos sus archivos con seguridad.", "We back up your files safely.", 60, 180, None),
    ("data_transfer", "Transferencia de datos", "Data-transfer assistance", "Pasamos su información a un equipo nuevo.", "We move your data to a new device.", 60, 180, None),
    ("printer_setup", "Instalación de impresora", "Printer setup", "Dejamos su impresora funcionando.", "We get your printer working.", 30, 90, {"bt": "instant", "pt": "fixed"}),
    ("printer_troubleshooting", "Solución de problemas de impresora", "Printer troubleshooting", "Arreglamos atascos y errores de impresión.", "Fixing jams and print errors.", 30, 90, None),
    ("wifi_setup", "Configuración de Wi-Fi", "Wi-Fi setup", "Instalamos y configuramos su red Wi-Fi.", "We set up and configure your Wi-Fi.", 45, 120, {"bt": "instant", "pt": "fixed", "kw": ["wifi"]}),
    ("wifi_troubleshooting", "Solución de problemas de Wi-Fi", "Wi-Fi troubleshooting", "Arreglamos internet lento o intermitente.", "Fixing slow or dropping internet.", 45, 120, {"kw": ["no tengo internet", "internet lento", "se cae el wifi"]}),
    ("router_install", "Instalación de router", "Router installation", "Instalación y configuración de routers.", "Installing and configuring routers.", 45, 90, None),
    ("mesh_wifi_install", "Instalación de Wi-Fi mesh", "Mesh Wi-Fi installation", "Cobertura Wi-Fi en toda la casa.", "Whole-home Wi-Fi coverage.", 60, 150, None),
    ("connectivity_diagnosis", "Diagnóstico de conectividad", "Internet connectivity diagnosis", "Encontramos por qué falla su conexión.", "We find why your connection fails.", 45, 90, None),
    ("smart_tv_setup", "Configuración de Smart TV", "Smart television setup", "Instalación y cuentas en su Smart TV.", "Setup and accounts on your smart TV.", 30, 90, {"bt": "instant", "pt": "fixed"}),
    ("camera_install_tech", "Instalación de cámaras", "Security-camera installation", "Cámaras Wi-Fi para su hogar o negocio.", "Wi-Fi cameras for home or business.", 90, 300, None),
    ("camera_troubleshooting", "Solución de problemas de cámaras", "Security-camera troubleshooting", "Arreglamos cámaras sin señal o sin grabación.", "Fixing cameras with no signal or recording.", 45, 120, None),
    ("video_doorbell_setup", "Configuración de timbre con cámara", "Video-doorbell setup", "Instalación de timbres inteligentes.", "Installing smart doorbells.", 45, 90, None),
    ("smart_home_install", "Instalación de dispositivos inteligentes", "Smart-home device installation", "Focos, enchufes y asistentes inteligentes.", "Smart bulbs, plugs and assistants.", 45, 120, None),
    ("email_setup", "Configuración de correo", "Email setup", "Configuramos su correo en todos sus equipos.", "Setting up email on all your devices.", 30, 60, {"bt": "instant", "pt": "fixed"}),
    ("m365_setup", "Configuración de Microsoft 365", "Microsoft 365 setup", "Instalación y cuentas de Microsoft 365.", "Microsoft 365 installation and accounts.", 45, 90, {"bt": "instant", "pt": "fixed"}),
    ("phone_setup", "Configuración de celular", "Mobile-phone setup", "Traspaso y configuración de celular nuevo.", "New-phone setup and data transfer.", 30, 90, {"bt": "instant", "pt": "fixed"}),
    ("cellphone_repair", "Reparación de celulares", "Cellphone repair", "Cambio de pantallas y baterías.", "Screen and battery replacement.", 45, 120, {"kw": ["pantalla rota"]}),
    ("tablet_setup", "Configuración de tablet", "Tablet setup", "Dejamos su tablet lista para usar.", "Getting your tablet ready to use.", 30, 60, {"bt": "instant", "pt": "fixed"}),
    ("remote_support", "Soporte técnico remoto", "Remote technical support", "Le ayudamos por conexión remota.", "We help you over a remote connection.", 30, 120, {"bt": "instant", "pt": "hourly"}),
    ("small_business_it", "Soporte TI para pequeños negocios", "Small-business IT support", "Soporte tecnológico para su negocio.", "Tech support for your business.", 60, 300, {"pt": "hourly"}),
]

_S["beauty"] = [
    ("mens_haircut", "Corte de cabello para hombre", "Men's haircut", "Corte de cabello masculino a domicilio.", "Men's haircut at home.", 30, 60, {"kw": ["peluquero"]}),
    ("womens_haircut", "Corte de cabello para mujer", "Women's haircut", "Corte femenino a domicilio.", "Women's haircut at home.", 45, 90, None),
    ("kids_haircut", "Corte de cabello para niños", "Children's haircut", "Cortes para niños con paciencia.", "Patient haircuts for kids.", 20, 45, None),
    ("beard_trim", "Arreglo de barba", "Beard trimming", "Perfilado y arreglo de barba.", "Beard shaping and trimming.", 20, 45, {"kw": ["barbero"]}),
    ("hairstyling", "Peinados", "Hairstyling", "Peinados para toda ocasión.", "Styling for any occasion.", 45, 120, None),
    ("blow_dry", "Cepillado", "Blow-dry service", "Secado y cepillado profesional.", "Professional blow-dry.", 30, 60, None),
    ("hair_coloring", "Tinturado de cabello", "Hair coloring", "Tintes y retoques a domicilio.", "Coloring and touch-ups at home.", 90, 240, {"bt": "estimate", "kw": ["tinte"]}),
    ("braiding", "Trenzas", "Braiding", "Trenzas y peinados trenzados.", "Braids and braided styles.", 60, 240, None),
    ("makeup", "Maquillaje", "Makeup", "Maquillaje profesional a domicilio.", "Professional makeup at home.", 45, 90, None),
    ("event_makeup", "Maquillaje para eventos", "Event makeup", "Maquillaje para bodas y eventos.", "Makeup for weddings and events.", 60, 120, None),
    ("manicure", "Manicure", "Manicure", "Manicure profesional a domicilio.", "Professional manicure at home.", 45, 90, {"kw": ["uñas"]}),
    ("pedicure", "Pedicure", "Pedicure", "Pedicure profesional a domicilio.", "Professional pedicure at home.", 45, 90, None),
    ("nail_application", "Aplicación de uñas", "Nail application", "Uñas acrílicas y en gel.", "Acrylic and gel nails.", 60, 150, None),
    ("nail_removal", "Retiro de uñas", "Nail removal", "Retiro seguro de acrílicas o gel.", "Safe removal of acrylics or gel.", 30, 60, None),
    ("eyebrow_shaping", "Perfilado de cejas", "Eyebrow shaping", "Diseño y depilación de cejas.", "Brow design and shaping.", 20, 45, {"kw": ["cejas"]}),
    ("eyelash_service", "Pestañas", "Eyelash service", "Extensiones y lifting de pestañas.", "Lash extensions and lifts.", 60, 150, None),
    ("facial_care", "Limpieza facial", "Facial care", "Limpieza facial no invasiva.", "Non-invasive facial cleansing.", 45, 90, None),
    ("beauty_consultation", "Asesoría de imagen no invasiva", "Non-invasive beauty consultation", "Asesoría de imagen y cuidado personal.", "Image and personal-care consultation.", 30, 60, None),
]

_S["automotive"] = [
    ("car_wash", "Lavado de auto", "Car washing", "Lavado completo de su vehículo.", "Complete wash for your vehicle.", 45, 120, {"kw": ["lavar carro"]}),
    ("mobile_car_wash", "Lavado de auto a domicilio", "Mobile car washing", "Lavamos su auto donde esté.", "We wash your car wherever it is.", 60, 120, None),
    ("interior_detailing", "Limpieza profunda interior", "Interior detailing", "Aspirado y detallado interior completo.", "Full interior vacuum and detail.", 90, 240, None),
    ("exterior_detailing", "Detallado exterior", "Exterior detailing", "Pulido y protección de pintura.", "Polishing and paint protection.", 120, 300, None),
    ("full_detailing", "Detallado completo", "Full detailing", "Interior y exterior como de agencia.", "Showroom-level inside and out.", 180, 420, None),
    ("battery_replacement", "Cambio de batería", "Battery replacement", "Cambio de batería a domicilio.", "Battery replacement wherever you are.", 30, 60, {"emergency": True, "kw": ["batería muerta", "no prende"]}),
    ("battery_jumpstart", "Paso de corriente", "Battery jump-start", "Arrancamos su auto con batería descargada.", "We jump-start your dead battery.", 20, 45, {"pt": "fixed", "emergency": True, "kw": ["se quedó sin batería"]}),
    ("oil_change", "Cambio de aceite", "Oil change", "Cambio de aceite y filtro a domicilio.", "Oil and filter change at your location.", 45, 90, {"pt": "fixed"}),
    ("tire_change", "Cambio de llanta", "Tire change", "Cambio o rotación de llantas.", "Tire change or rotation.", 30, 90, {"emergency": True, "kw": ["llanta baja"]}),
    ("flat_tire_assistance", "Auxilio por llanta pinchada", "Flat-tire assistance", "Vamos donde está y cambiamos la llanta.", "We come to you and change the flat.", 30, 60, {"pt": "fixed", "emergency": True, "kw": ["llanta pinchada"]}),
    ("brake_inspection", "Revisión de frenos", "Brake inspection", "Inspección del estado de sus frenos.", "Checking the condition of your brakes.", 45, 90, {"bt": "estimate", "pt": "inspection_fee", "risk": "high"}),
    ("basic_diagnosis", "Diagnóstico mecánico básico", "Basic mechanical diagnosis", "Revisión general para detectar fallas.", "General check to detect faults.", 45, 120, {"bt": "estimate", "pt": "inspection_fee"}),
    ("vehicle_scanning", "Escaneo del vehículo", "Vehicle scanning", "Escaneo computarizado de códigos de falla.", "Computer scan of fault codes.", 30, 60, {"pt": "fixed", "kw": ["check engine"]}),
    ("headlight_replacement", "Cambio de focos del auto", "Headlight replacement", "Cambio de focos delanteros o posteriores.", "Replacing head or tail lamps.", 20, 60, {"pt": "per_item"}),
    ("wiper_replacement", "Cambio de plumas limpiaparabrisas", "Windshield-wiper replacement", "Plumas nuevas instaladas al instante.", "New wipers installed on the spot.", 15, 30, {"pt": "per_item"}),
    ("air_filter_replacement", "Cambio de filtro de aire", "Air-filter replacement", "Cambio del filtro de aire del motor.", "Engine air-filter replacement.", 15, 45, {"pt": "fixed"}),
    ("cabin_filter_replacement", "Cambio de filtro de cabina", "Cabin-filter replacement", "Aire más limpio dentro del auto.", "Cleaner air inside the car.", 15, 45, {"pt": "fixed"}),
    ("vehicle_pickup", "Traslado del vehículo a taller", "Vehicle pickup for service", "Llevamos su auto al taller y lo devolvemos.", "We take your car to the shop and back.", 60, 240, {"bt": "estimate"}),
    ("roadside_assistance", "Auxilio vial de emergencia", "Emergency roadside assistance", "Ayuda en carretera cuando la necesita.", "Help on the road when you need it.", 30, 120, {"pt": "starting_at", "emergency": True, "kw": ["grúa", "auxilio"]}),
]

_S["moving"] = [
    ("small_move", "Mudanza pequeña", "Small move", "Mudanzas de pocos muebles o cajas.", "Moves with a few items or boxes.", 120, 360, {"kw": ["mudanza barata"]}),
    ("apartment_move", "Mudanza de departamento", "Apartment move", "Mudanza completa de departamento.", "Full apartment move.", 240, 600, {"bt": "estimate"}),
    ("furniture_moving", "Traslado de muebles", "Furniture moving", "Movemos muebles dentro o entre casas.", "Moving furniture within or between homes.", 60, 240, None),
    ("loading_help", "Ayuda para cargar", "Loading assistance", "Cargadores para su camión o camioneta.", "Loaders for your truck or van.", 60, 240, {"pt": "hourly"}),
    ("unloading_help", "Ayuda para descargar", "Unloading assistance", "Descargamos su camión o contenedor.", "We unload your truck or container.", 60, 240, {"pt": "hourly"}),
    ("appliance_moving", "Traslado de electrodomésticos", "Appliance moving", "Movemos refris, lavadoras y cocinas.", "We move fridges, washers and stoves.", 60, 180, {"pt": "per_item"}),
    ("packing_help", "Ayuda de embalaje", "Packing assistance", "Empacamos sus cosas con cuidado.", "We pack your things with care.", 120, 360, {"pt": "hourly"}),
    ("unpacking_help", "Ayuda para desempacar", "Unpacking assistance", "Desempacamos y organizamos.", "We unpack and organize.", 120, 360, {"pt": "hourly"}),
    ("furniture_disassembly", "Desarmado de muebles", "Furniture disassembly", "Desarmamos muebles para el traslado.", "We take furniture apart for the move.", 30, 120, {"pt": "per_item"}),
    ("furniture_reassembly", "Armado de muebles (mudanza)", "Furniture reassembly", "Armamos sus muebles en el nuevo hogar.", "We reassemble furniture in your new home.", 30, 120, {"pt": "per_item"}),
    ("pickup_delivery", "Retiro y entrega", "Pickup and delivery", "Recogemos y entregamos sus compras.", "We pick up and deliver your purchases.", 60, 180, None),
    ("store_pickup", "Retiro en tienda", "Store pickup", "Retiramos su compra de la tienda.", "We collect your purchase from the store.", 60, 180, None),
    ("document_delivery", "Entrega de documentos", "Document delivery", "Mensajería de documentos en la ciudad.", "Same-city document courier.", 30, 120, {"pt": "fixed"}),
    ("small_package_delivery", "Entrega de paquetes pequeños", "Small-package delivery", "Entregas rápidas de paquetes.", "Fast small-package deliveries.", 30, 120, {"pt": "fixed"}),
    ("material_delivery", "Transporte de materiales de construcción", "Construction-material delivery", "Llevamos materiales a su obra.", "We haul materials to your site.", 60, 240, {"bt": "estimate"}),
    ("debris_transport", "Transporte de escombros", "Debris transport", "Retiramos escombros y desechos.", "We haul away debris and waste.", 60, 240, {"bt": "estimate"}),
    ("moving_truck_help", "Ayudantes con camión de mudanza", "Moving-truck assistance", "Camión y cargadores para su mudanza.", "Truck and movers for your move.", 240, 600, {"bt": "estimate"}),
]

_S["home_security"] = [
    ("camera_install", "Instalación de cámaras de seguridad", "Security-camera installation", "Instalación profesional de cámaras.", "Professional camera installation.", 120, 360, {"kw": ["cctv"]}),
    ("camera_config", "Configuración de cámaras", "Camera configuration", "Configuración y acceso desde su celular.", "Setup and phone access for your cameras.", 45, 120, None),
    ("camera_maintenance", "Mantenimiento de cámaras", "Camera maintenance", "Limpieza y revisión de su sistema.", "Cleaning and checkup of your system.", 60, 120, {"bt": "instant", "pt": "fixed"}),
    ("alarm_install", "Instalación de alarmas", "Alarm-system installation", "Sistemas de alarma para casa o negocio.", "Alarm systems for home or business.", 120, 360, None),
    ("alarm_troubleshooting", "Solución de problemas de alarma", "Alarm troubleshooting", "Arreglamos alarmas que fallan o suenan solas.", "Fixing faulty or false-triggering alarms.", 60, 150, None),
    ("smart_lock_install", "Instalación de cerraduras inteligentes", "Smart-lock installation", "Cerraduras con clave, huella o app.", "Locks with code, fingerprint or app.", 45, 120, None),
    ("doorbell_camera_install", "Instalación de timbre con cámara", "Doorbell-camera installation", "Vea quién llama desde su celular.", "See who's at the door from your phone.", 45, 120, None),
    ("motion_sensor_security", "Instalación de sensores de movimiento", "Motion-sensor installation", "Sensores para alarmas y luces.", "Sensors for alarms and lights.", 45, 120, None),
    ("security_assessment", "Evaluación de seguridad del hogar", "Home-security assessment", "Informe de puntos débiles y mejoras.", "Report on weak spots and improvements.", 60, 120, {"pt": "inspection_fee"}),
    ("access_control_install", "Instalación de control de acceso", "Access-control installation", "Control de acceso para edificios y oficinas.", "Access control for buildings and offices.", 120, 480, None),
    ("intercom_install", "Instalación de citófono", "Intercom installation", "Citófonos e intercomunicadores.", "Intercom systems.", 90, 240, {"kw": ["citófono", "portero"]}),
]

_S["pets"] = [
    ("dog_walking", "Paseo de perros", "Dog walking", "Paseos con cariño y seguridad.", "Caring, safe dog walks.", 30, 90, {"kw": ["pasear perro", "paseador"]}),
    ("pet_sitting", "Cuidado de mascotas", "Pet sitting", "Cuidamos su mascota mientras no está.", "We care for your pet while you're away.", 120, 1440, {"pt": "hourly"}),
    ("pet_feeding", "Alimentación de mascotas", "Pet feeding", "Visitas para alimentar a su mascota.", "Visits to feed your pet.", 20, 45, None),
    ("home_pet_visit", "Visita a domicilio para mascotas", "Home pet visit", "Compañía y cuidado en su propia casa.", "Company and care in your own home.", 30, 90, None),
    ("basic_grooming", "Peluquería básica de mascotas", "Basic pet grooming", "Corte y arreglo básico no veterinario.", "Basic non-veterinary trim and tidy-up.", 60, 150, None),
    ("pet_bathing", "Baño de mascotas", "Pet bathing", "Baño y secado a domicilio.", "Bathing and drying at home.", 45, 120, None),
    ("pet_transport", "Transporte de mascotas", "Pet transportation", "Llevamos su mascota con seguridad.", "We transport your pet safely.", 30, 120, None),
    ("litter_box_cleaning", "Limpieza de arenero", "Litter-box cleaning", "Limpieza y cambio de arena.", "Litter cleaning and replacement.", 20, 45, None),
    ("yard_pet_waste_cleanup", "Limpieza de desechos en el patio", "Yard pet-waste cleanup", "Patio limpio y sin malos olores.", "A clean, odor-free yard.", 30, 90, None),
]

_S["events"] = [
    ("event_cleaning", "Limpieza de eventos", "Event cleaning", "Limpieza antes, durante o después del evento.", "Cleaning before, during or after your event.", 120, 480, None),
    ("waitstaff", "Meseros para eventos", "Waitstaff", "Meseros profesionales para su evento.", "Professional waitstaff for your event.", 240, 600, {"pt": "hourly"}),
    ("event_setup", "Montaje de eventos", "Event setup", "Armamos todo antes de que lleguen los invitados.", "We set everything up before guests arrive.", 120, 480, None),
    ("event_teardown", "Desmontaje de eventos", "Event teardown", "Desmontamos y recogemos al finalizar.", "We tear down and clean up afterward.", 120, 360, None),
    ("decoration_help", "Ayuda con decoración", "Decoration assistance", "Ayuda para decorar su celebración.", "Help decorating your celebration.", 120, 480, None),
    ("table_chair_setup", "Armado de mesas y sillas", "Table and chair setup", "Colocación de mobiliario para eventos.", "Setting up event furniture.", 60, 240, None),
    ("photographer", "Fotógrafo", "Photographer", "Fotografía profesional de eventos.", "Professional event photography.", 120, 480, None),
    ("videographer", "Videógrafo", "Videographer", "Video profesional de su evento.", "Professional event video.", 120, 480, None),
    ("dj", "DJ", "DJ", "Música y ambiente para su fiesta.", "Music and atmosphere for your party.", 240, 600, None),
    ("sound_setup", "Instalación de sonido", "Sound-system setup", "Equipos de sonido instalados y operados.", "Sound systems set up and run.", 120, 480, None),
    ("lighting_setup", "Instalación de iluminación", "Lighting setup", "Iluminación decorativa y de escenario.", "Decorative and stage lighting.", 120, 480, None),
    ("catering_help", "Ayuda de catering", "Catering assistance", "Apoyo en cocina y servicio de alimentos.", "Kitchen and food-service support.", 240, 600, {"pt": "hourly"}),
    ("event_makeup_svc", "Maquillaje para eventos", "Makeup for events", "Maquillaje profesional el día del evento.", "Professional makeup on the day.", 60, 120, None),
    ("event_hairstyling", "Peinados para eventos", "Hairstyling for events", "Peinados para novias e invitadas.", "Styling for brides and guests.", 60, 150, None),
    ("event_security_support", "Apoyo de seguridad para eventos", "Event security support", "Personal de apoyo donde la ley lo permita.", "Support staff where legally permitted.", 240, 600, {"pt": "hourly", "ver": "enhanced"}),
]

_S["business_support"] = [
    ("document_typing", "Digitación de documentos", "Document typing", "Transcribimos y digitamos sus documentos.", "We type up and transcribe your documents.", 60, 300, None),
    ("data_entry", "Ingreso de datos", "Data entry", "Ingreso de datos preciso y rápido.", "Fast, accurate data entry.", 60, 480, None),
    ("spreadsheet_creation", "Creación de hojas de cálculo", "Spreadsheet creation", "Hojas de Excel a su medida.", "Custom Excel spreadsheets.", 60, 300, None),
    ("resume_preparation", "Elaboración de hoja de vida", "Resume preparation", "Hojas de vida que destacan.", "Resumes that stand out.", 60, 120, {"pt": "fixed", "kw": ["cv", "hoja de vida"]}),
    ("translation", "Traducción", "Translation", "Traducciones español-inglés no oficiales.", "Non-certified Spanish-English translation.", 60, 300, {"pt": "per_item"}),
    ("basic_graphic_design", "Diseño gráfico básico", "Basic graphic design", "Logos, afiches y artes para redes.", "Logos, flyers and social artwork.", 120, 480, {"bt": "estimate"}),
    ("social_media_help", "Ayuda con redes sociales", "Social-media assistance", "Manejo básico de sus redes.", "Basic handling of your social accounts.", 60, 300, None),
    ("product_photography", "Fotografía de productos", "Product photography", "Fotos profesionales de sus productos.", "Professional photos of your products.", 120, 300, {"bt": "estimate"}),
    ("inventory_help", "Ayuda con inventarios", "Inventory assistance", "Conteo y organización de inventario.", "Inventory counting and organizing.", 120, 480, None),
    ("virtual_assistance", "Asistencia virtual administrativa", "Administrative virtual assistance", "Apoyo administrativo remoto.", "Remote administrative support.", 60, 480, None),
    ("basic_bookkeeping", "Apoyo contable básico (no regulado)", "Basic bookkeeping support", "Organización de registros; no somos contadores públicos.", "Organizing records; not certified accountants.", 120, 480, None),
    ("business_computer_setup", "Instalación de computadoras para negocios", "Computer setup for small businesses", "Equipos listos para su local o consultorio.", "Machines ready for your shop or practice.", 60, 240, None),
    ("website_maintenance", "Mantenimiento de sitios web", "Website maintenance", "Actualizaciones y respaldos de su sitio.", "Updates and backups for your site.", 60, 240, {"bt": "estimate"}),
    ("delivery_coordination", "Coordinación de entregas locales", "Local delivery coordination", "Organizamos sus entregas del día.", "We organize your daily deliveries.", 120, 480, None),
]

# ── Loader ───────────────────────────────────────────────────────────────────

def _build():
    from professions import PROFESSIONS
    all_services = []
    for cat_key, entries in _S.items():
        defaults = CATEGORY_DEFAULTS[cat_key]
        cat_kw = CATEGORY_KEYWORDS.get(cat_key, [])
        icon = PROFESSIONS.get(cat_key, {}).get("icon", "")
        for order, (key, es, en, desc_es, desc_en, dmin, dmax, ov) in enumerate(entries):
            o = ov or {}
            all_services.append({
                "key": key,
                "category": cat_key,
                "profession": cat_key,  # v1: profession ≡ category
                "name_es": es,
                "name_en": en,
                "description_es": desc_es,
                "description_en": desc_en,
                "icon": o.get("icon", icon),
                "booking_type": o.get("bt", defaults["bt"]),
                "pricing_type": o.get("pt", defaults["pt"]),
                "duration_min": dmin,
                "duration_max": dmax,
                "materials_possible": o.get("materials", defaults["materials"]),
                "photos_requested": o.get("photos", defaults["photos"]),
                "risk_level": o.get("risk", defaults["risk"]),
                "verification_required": o.get("ver", defaults["ver"]),
                "emergency_capable": o.get("emergency", False),
                "keywords": cat_kw + o.get("kw", []),
                "questions": QUESTION_SETS.get(cat_key, QUESTION_SETS["_default"]),
                "sort_order": order,
                "is_active": True,
            })
    return all_services


ALL_SERVICES = _build()
SERVICES_BY_KEY = {s["key"]: s for s in ALL_SERVICES}
SERVICE_KEYS = list(SERVICES_BY_KEY.keys())


def _norm(text: str) -> str:
    """Lowercase and strip accents so 'plomería' matches 'plomeria'."""
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
    )


def search_services(query: str, lang: str = "es", limit: int = 20) -> list[dict]:
    """Rank services by match against name, description and keywords.

    Simple scored substring match — intentionally dependency-free. Name hits
    rank above keyword hits, which rank above description hits.
    """
    q = _norm(query.strip())
    if not q:
        return []
    terms = q.split()
    scored = []
    for s in ALL_SERVICES:
        if not s["is_active"]:
            continue
        name = _norm(s["name_es"] if lang == "es" else s["name_en"])
        desc = _norm(s["description_es"] if lang == "es" else s["description_en"])
        kws = [_norm(k) for k in s["keywords"]]
        score = 0
        for t in terms:
            if t in name:
                score += 10
            if any(t in k for k in kws):
                score += 6
            if t in desc:
                score += 2
        # Whole-phrase bonus
        if q in name:
            score += 15
        if any(q in k for k in kws):
            score += 10
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: (-x[0], x[1]["sort_order"]))
    return [s for _, s in scored[:limit]]
