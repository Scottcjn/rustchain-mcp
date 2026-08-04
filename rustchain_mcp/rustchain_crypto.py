"""
RustChain Cryptographic Module
==============================
Ed25519 wallet operations for RustChain MCP Server.

Provides secure wallet generation, signing, and keystore management
using Ed25519 cryptography compatible with the RustChain blockchain.

Security:
- Private keys are encrypted at rest using Fernet (AES-128-CBC)
- Seed phrases are generated using BIP39-compatible mnemonic generation
- Never expose private keys or seed phrases in tool responses
"""

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

# Use cryptography library for Ed25519 (available in Python 3.8+)
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

# Alternative: use nacl (PyNaCl) if available
try:
    import nacl.signing as nacl_signing
    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False

# Fallback to ed25519 library
try:
    import ed25519
    ED25519_AVAILABLE = True
except ImportError:
    ED25519_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════
# BIP39 Wordlist (official 2048-word English list, BIP-0039)
# 2048 == 2^11 so each 11-bit index maps to exactly one word (full entropy, standards-compliant)
# ═══════════════════════════════════════════════════════════════
BIP39_WORDLIST = [
    "abandon", "ability", "able", "about", "above", "absent", "absorb", "abstract",
    "absurd", "abuse", "access", "accident", "account", "accuse", "achieve", "acid",
    "acoustic", "acquire", "across", "act", "action", "actor", "actress", "actual",
    "adapt", "add", "addict", "address", "adjust", "admit", "adult", "advance",
    "advice", "aerobic", "affair", "afford", "afraid", "again", "age", "agent",
    "agree", "ahead", "aim", "air", "airport", "aisle", "alarm", "album",
    "alcohol", "alert", "alien", "all", "alley", "allow", "almost", "alone",
    "alpha", "already", "also", "alter", "always", "amateur", "amazing", "among",
    "amount", "amused", "analyst", "anchor", "ancient", "anger", "angle", "angry",
    "animal", "ankle", "announce", "annual", "another", "answer", "antenna", "antique",
    "anxiety", "any", "apart", "apology", "appear", "apple", "approve", "april",
    "arch", "arctic", "area", "arena", "argue", "arm", "armed", "armor",
    "army", "around", "arrange", "arrest", "arrive", "arrow", "art", "artefact",
    "artist", "artwork", "ask", "aspect", "assault", "asset", "assist", "assume",
    "asthma", "athlete", "atom", "attack", "attend", "attitude", "attract", "auction",
    "audit", "august", "aunt", "author", "auto", "autumn", "average", "avocado",
    "avoid", "awake", "aware", "away", "awesome", "awful", "awkward", "axis",
    "baby", "bachelor", "bacon", "badge", "bag", "balance", "balcony", "ball",
    "bamboo", "banana", "banner", "bar", "barely", "bargain", "barrel", "base",
    "basic", "basket", "battle", "beach", "bean", "beauty", "because", "become",
    "beef", "before", "begin", "behave", "behind", "believe", "below", "belt",
    "bench", "benefit", "best", "betray", "better", "between", "beyond", "bicycle",
    "bid", "bike", "bind", "biology", "bird", "birth", "bitter", "black",
    "blade", "blame", "blanket", "blast", "bleak", "bless", "blind", "blood",
    "blossom", "blouse", "blue", "blur", "blush", "board", "boat", "body",
    "boil", "bomb", "bone", "bonus", "book", "boost", "border", "boring",
    "borrow", "boss", "bottom", "bounce", "box", "boy", "bracket", "brain",
    "brand", "brass", "brave", "bread", "breeze", "brick", "bridge", "brief",
    "bright", "bring", "brisk", "broccoli", "broken", "bronze", "broom", "brother",
    "brown", "brush", "bubble", "buddy", "budget", "buffalo", "build", "bulb",
    "bulk", "bullet", "bundle", "bunker", "burden", "burger", "burst", "bus",
    "business", "busy", "butter", "buyer", "buzz", "cabbage", "cabin", "cable",
    "cactus", "cage", "cake", "call", "calm", "camera", "camp", "can",
    "canal", "cancel", "candy", "cannon", "canoe", "canvas", "canyon", "capable",
    "capital", "captain", "car", "carbon", "card", "cargo", "carpet", "carry",
    "cart", "case", "cash", "casino", "castle", "casual", "cat", "catalog",
    "catch", "category", "cattle", "caught", "cause", "caution", "cave", "ceiling",
    "celery", "cement", "census", "century", "cereal", "certain", "chair", "chalk",
    "champion", "change", "chaos", "chapter", "charge", "chase", "chat", "cheap",
    "check", "cheese", "chef", "cherry", "chest", "chicken", "chief", "child",
    "chimney", "choice", "choose", "chronic", "chuckle", "chunk", "churn", "cigar",
    "cinnamon", "circle", "citizen", "city", "civil", "claim", "clap", "clarify",
    "claw", "clay", "clean", "clerk", "clever", "click", "client", "cliff",
    "climb", "clinic", "clip", "clock", "clog", "close", "cloth", "cloud",
    "clown", "club", "clump", "cluster", "clutch", "coach", "coast", "coconut",
    "code", "coffee", "coil", "coin", "collect", "color", "column", "combine",
    "come", "comfort", "comic", "common", "company", "concert", "conduct", "confirm",
    "congress", "connect", "consider", "control", "convince", "cook", "cool", "copper",
    "copy", "coral", "core", "corn", "correct", "cost", "cotton", "couch",
    "country", "couple", "course", "cousin", "cover", "coyote", "crack", "cradle",
    "craft", "cram", "crane", "crash", "crater", "crawl", "crazy", "cream",
    "credit", "creek", "crew", "cricket", "crime", "crisp", "critic", "crop",
    "cross", "crouch", "crowd", "crucial", "cruel", "cruise", "crumble", "crunch",
    "crush", "cry", "crystal", "cube", "culture", "cup", "cupboard", "curious",
    "current", "curtain", "curve", "cushion", "custom", "cute", "cycle", "dad",
    "damage", "damp", "dance", "danger", "daring", "dash", "daughter", "dawn",
    "day", "deal", "debate", "debris", "decade", "december", "decide", "decline",
    "decorate", "decrease", "deer", "defense", "define", "defy", "degree", "delay",
    "deliver", "demand", "demise", "denial", "dentist", "deny", "depart", "depend",
    "deposit", "depth", "deputy", "derive", "describe", "desert", "design", "desk",
    "despair", "destroy", "detail", "detect", "develop", "device", "devote", "diagram",
    "dial", "diamond", "diary", "dice", "diesel", "diet", "differ", "digital",
    "dignity", "dilemma", "dinner", "dinosaur", "direct", "dirt", "disagree", "discover",
    "disease", "dish", "dismiss", "disorder", "display", "distance", "divert", "divide",
    "divorce", "dizzy", "doctor", "document", "dog", "doll", "dolphin", "domain",
    "donate", "donkey", "donor", "door", "dose", "double", "dove", "draft",
    "dragon", "drama", "drastic", "draw", "dream", "dress", "drift", "drill",
    "drink", "drip", "drive", "drop", "drum", "dry", "duck", "dumb",
    "dune", "during", "dust", "dutch", "duty", "dwarf", "dynamic", "eager",
    "eagle", "early", "earn", "earth", "easily", "east", "easy", "echo",
    "ecology", "economy", "edge", "edit", "educate", "effort", "egg", "eight",
    "either", "elbow", "elder", "electric", "elegant", "element", "elephant", "elevator",
    "elite", "else", "embark", "embody", "embrace", "emerge", "emotion", "employ",
    "empower", "empty", "enable", "enact", "end", "endless", "endorse", "enemy",
    "energy", "enforce", "engage", "engine", "enhance", "enjoy", "enlist", "enough",
    "enrich", "enroll", "ensure", "enter", "entire", "entry", "envelope", "episode",
    "equal", "equip", "era", "erase", "erode", "erosion", "error", "erupt",
    "escape", "essay", "essence", "estate", "eternal", "ethics", "evidence", "evil",
    "evoke", "evolve", "exact", "example", "excess", "exchange", "excite", "exclude",
    "excuse", "execute", "exercise", "exhaust", "exhibit", "exile", "exist", "exit",
    "exotic", "expand", "expect", "expire", "explain", "expose", "express", "extend",
    "extra", "eye", "eyebrow", "fabric", "face", "faculty", "fade", "faint",
    "faith", "fall", "false", "fame", "family", "famous", "fan", "fancy",
    "fantasy", "farm", "fashion", "fat", "fatal", "father", "fatigue", "fault",
    "favorite", "feature", "february", "federal", "fee", "feed", "feel", "female",
    "fence", "festival", "fetch", "fever", "few", "fiber", "fiction", "field",
    "figure", "file", "film", "filter", "final", "find", "fine", "finger",
    "finish", "fire", "firm", "first", "fiscal", "fish", "fit", "fitness",
    "fix", "flag", "flame", "flash", "flat", "flavor", "flee", "flight",
    "flip", "float", "flock", "floor", "flower", "fluid", "flush", "fly",
    "foam", "focus", "fog", "foil", "fold", "follow", "food", "foot",
    "force", "forest", "forget", "fork", "fortune", "forum", "forward", "fossil",
    "foster", "found", "fox", "fragile", "frame", "frequent", "fresh", "friend",
    "fringe", "frog", "front", "frost", "frown", "frozen", "fruit", "fuel",
    "fun", "funny", "furnace", "fury", "future", "gadget", "gain", "galaxy",
    "gallery", "game", "gap", "garage", "garbage", "garden", "garlic", "garment",
    "gas", "gasp", "gate", "gather", "gauge", "gaze", "general", "genius",
    "genre", "gentle", "genuine", "gesture", "ghost", "giant", "gift", "giggle",
    "ginger", "giraffe", "girl", "give", "glad", "glance", "glare", "glass",
    "glide", "glimpse", "globe", "gloom", "glory", "glove", "glow", "glue",
    "goat", "goddess", "gold", "good", "goose", "gorilla", "gospel", "gossip",
    "govern", "gown", "grab", "grace", "grain", "grant", "grape", "grass",
    "gravity", "great", "green", "grid", "grief", "grit", "grocery", "group",
    "grow", "grunt", "guard", "guess", "guide", "guilt", "guitar", "gun",
    "gym", "habit", "hair", "half", "hammer", "hamster", "hand", "happy",
    "harbor", "hard", "harsh", "harvest", "hat", "have", "hawk", "hazard",
    "head", "health", "heart", "heavy", "hedgehog", "height", "hello", "helmet",
    "help", "hen", "hero", "hidden", "high", "hill", "hint", "hip",
    "hire", "history", "hobby", "hockey", "hold", "hole", "holiday", "hollow",
    "home", "honey", "hood", "hope", "horn", "horror", "horse", "hospital",
    "host", "hotel", "hour", "hover", "hub", "huge", "human", "humble",
    "humor", "hundred", "hungry", "hunt", "hurdle", "hurry", "hurt", "husband",
    "hybrid", "ice", "icon", "idea", "identify", "idle", "ignore", "ill",
    "illegal", "illness", "image", "imitate", "immense", "immune", "impact", "impose",
    "improve", "impulse", "inch", "include", "income", "increase", "index", "indicate",
    "indoor", "industry", "infant", "inflict", "inform", "inhale", "inherit", "initial",
    "inject", "injury", "inmate", "inner", "innocent", "input", "inquiry", "insane",
    "insect", "inside", "inspire", "install", "intact", "interest", "into", "invest",
    "invite", "involve", "iron", "island", "isolate", "issue", "item", "ivory",
    "jacket", "jaguar", "jar", "jazz", "jealous", "jeans", "jelly", "jewel",
    "job", "join", "joke", "journey", "joy", "judge", "juice", "jump",
    "jungle", "junior", "junk", "just", "kangaroo", "keen", "keep", "ketchup",
    "key", "kick", "kid", "kidney", "kind", "kingdom", "kiss", "kit",
    "kitchen", "kite", "kitten", "kiwi", "knee", "knife", "knock", "know",
    "lab", "label", "labor", "ladder", "lady", "lake", "lamp", "language",
    "laptop", "large", "later", "latin", "laugh", "laundry", "lava", "law",
    "lawn", "lawsuit", "layer", "lazy", "leader", "leaf", "learn", "leave",
    "lecture", "left", "leg", "legal", "legend", "leisure", "lemon", "lend",
    "length", "lens", "leopard", "lesson", "letter", "level", "liar", "liberty",
    "library", "license", "life", "lift", "light", "like", "limb", "limit",
    "link", "lion", "liquid", "list", "little", "live", "lizard", "load",
    "loan", "lobster", "local", "lock", "logic", "lonely", "long", "loop",
    "lottery", "loud", "lounge", "love", "loyal", "lucky", "luggage", "lumber",
    "lunar", "lunch", "luxury", "lyrics", "machine", "mad", "magic", "magnet",
    "maid", "mail", "main", "major", "make", "mammal", "man", "manage",
    "mandate", "mango", "mansion", "manual", "maple", "marble", "march", "margin",
    "marine", "market", "marriage", "mask", "mass", "master", "match", "material",
    "math", "matrix", "matter", "maximum", "maze", "meadow", "mean", "measure",
    "meat", "mechanic", "medal", "media", "melody", "melt", "member", "memory",
    "mention", "menu", "mercy", "merge", "merit", "merry", "mesh", "message",
    "metal", "method", "middle", "midnight", "milk", "million", "mimic", "mind",
    "minimum", "minor", "minute", "miracle", "mirror", "misery", "miss", "mistake",
    "mix", "mixed", "mixture", "mobile", "model", "modify", "mom", "moment",
    "monitor", "monkey", "monster", "month", "moon", "moral", "more", "morning",
    "mosquito", "mother", "motion", "motor", "mountain", "mouse", "move", "movie",
    "much", "muffin", "mule", "multiply", "muscle", "museum", "mushroom", "music",
    "must", "mutual", "myself", "mystery", "myth", "naive", "name", "napkin",
    "narrow", "nasty", "nation", "nature", "near", "neck", "need", "negative",
    "neglect", "neither", "nephew", "nerve", "nest", "net", "network", "neutral",
    "never", "news", "next", "nice", "night", "noble", "noise", "nominee",
    "noodle", "normal", "north", "nose", "notable", "note", "nothing", "notice",
    "novel", "now", "nuclear", "number", "nurse", "nut", "oak", "obey",
    "object", "oblige", "obscure", "observe", "obtain", "obvious", "occur", "ocean",
    "october", "odor", "off", "offer", "office", "often", "oil", "okay",
    "old", "olive", "olympic", "omit", "once", "one", "onion", "online",
    "only", "open", "opera", "opinion", "oppose", "option", "orange", "orbit",
    "orchard", "order", "ordinary", "organ", "orient", "original", "orphan", "ostrich",
    "other", "outdoor", "outer", "output", "outside", "oval", "oven", "over",
    "own", "owner", "oxygen", "oyster", "ozone", "pact", "paddle", "page",
    "pair", "palace", "palm", "panda", "panel", "panic", "panther", "paper",
    "parade", "parent", "park", "parrot", "party", "pass", "patch", "path",
    "patient", "patrol", "pattern", "pause", "pave", "payment", "peace", "peanut",
    "pear", "peasant", "pelican", "pen", "penalty", "pencil", "people", "pepper",
    "perfect", "permit", "person", "pet", "phone", "photo", "phrase", "physical",
    "piano", "picnic", "picture", "piece", "pig", "pigeon", "pill", "pilot",
    "pink", "pioneer", "pipe", "pistol", "pitch", "pizza", "place", "planet",
    "plastic", "plate", "play", "please", "pledge", "pluck", "plug", "plunge",
    "poem", "poet", "point", "polar", "pole", "police", "pond", "pony",
    "pool", "popular", "portion", "position", "possible", "post", "potato", "pottery",
    "poverty", "powder", "power", "practice", "praise", "predict", "prefer", "prepare",
    "present", "pretty", "prevent", "price", "pride", "primary", "print", "priority",
    "prison", "private", "prize", "problem", "process", "produce", "profit", "program",
    "project", "promote", "proof", "property", "prosper", "protect", "proud", "provide",
    "public", "pudding", "pull", "pulp", "pulse", "pumpkin", "punch", "pupil",
    "puppy", "purchase", "purity", "purpose", "purse", "push", "put", "puzzle",
    "pyramid", "quality", "quantum", "quarter", "question", "quick", "quit", "quiz",
    "quote", "rabbit", "raccoon", "race", "rack", "radar", "radio", "rail",
    "rain", "raise", "rally", "ramp", "ranch", "random", "range", "rapid",
    "rare", "rate", "rather", "raven", "raw", "razor", "ready", "real",
    "reason", "rebel", "rebuild", "recall", "receive", "recipe", "record", "recycle",
    "reduce", "reflect", "reform", "refuse", "region", "regret", "regular", "reject",
    "relax", "release", "relief", "rely", "remain", "remember", "remind", "remove",
    "render", "renew", "rent", "reopen", "repair", "repeat", "replace", "report",
    "require", "rescue", "resemble", "resist", "resource", "response", "result", "retire",
    "retreat", "return", "reunion", "reveal", "review", "reward", "rhythm", "rib",
    "ribbon", "rice", "rich", "ride", "ridge", "rifle", "right", "rigid",
    "ring", "riot", "ripple", "risk", "ritual", "rival", "river", "road",
    "roast", "robot", "robust", "rocket", "romance", "roof", "rookie", "room",
    "rose", "rotate", "rough", "round", "route", "royal", "rubber", "rude",
    "rug", "rule", "run", "runway", "rural", "sad", "saddle", "sadness",
    "safe", "sail", "salad", "salmon", "salon", "salt", "salute", "same",
    "sample", "sand", "satisfy", "satoshi", "sauce", "sausage", "save", "say",
    "scale", "scan", "scare", "scatter", "scene", "scheme", "school", "science",
    "scissors", "scorpion", "scout", "scrap", "screen", "script", "scrub", "sea",
    "search", "season", "seat", "second", "secret", "section", "security", "seed",
    "seek", "segment", "select", "sell", "seminar", "senior", "sense", "sentence",
    "series", "service", "session", "settle", "setup", "seven", "shadow", "shaft",
    "shallow", "share", "shed", "shell", "sheriff", "shield", "shift", "shine",
    "ship", "shiver", "shock", "shoe", "shoot", "shop", "short", "shoulder",
    "shove", "shrimp", "shrug", "shuffle", "shy", "sibling", "sick", "side",
    "siege", "sight", "sign", "silent", "silk", "silly", "silver", "similar",
    "simple", "since", "sing", "siren", "sister", "situate", "six", "size",
    "skate", "sketch", "ski", "skill", "skin", "skirt", "skull", "slab",
    "slam", "sleep", "slender", "slice", "slide", "slight", "slim", "slogan",
    "slot", "slow", "slush", "small", "smart", "smile", "smoke", "smooth",
    "snack", "snake", "snap", "sniff", "snow", "soap", "soccer", "social",
    "sock", "soda", "soft", "solar", "soldier", "solid", "solution", "solve",
    "someone", "song", "soon", "sorry", "sort", "soul", "sound", "soup",
    "source", "south", "space", "spare", "spatial", "spawn", "speak", "special",
    "speed", "spell", "spend", "sphere", "spice", "spider", "spike", "spin",
    "spirit", "split", "spoil", "sponsor", "spoon", "sport", "spot", "spray",
    "spread", "spring", "spy", "square", "squeeze", "squirrel", "stable", "stadium",
    "staff", "stage", "stairs", "stamp", "stand", "start", "state", "stay",
    "steak", "steel", "stem", "step", "stereo", "stick", "still", "sting",
    "stock", "stomach", "stone", "stool", "story", "stove", "strategy", "street",
    "strike", "strong", "struggle", "student", "stuff", "stumble", "style", "subject",
    "submit", "subway", "success", "such", "sudden", "suffer", "sugar", "suggest",
    "suit", "summer", "sun", "sunny", "sunset", "super", "supply", "supreme",
    "sure", "surface", "surge", "surprise", "surround", "survey", "suspect", "sustain",
    "swallow", "swamp", "swap", "swarm", "swear", "sweet", "swift", "swim",
    "swing", "switch", "sword", "symbol", "symptom", "syrup", "system", "table",
    "tackle", "tag", "tail", "talent", "talk", "tank", "tape", "target",
    "task", "taste", "tattoo", "taxi", "teach", "team", "tell", "ten",
    "tenant", "tennis", "tent", "term", "test", "text", "thank", "that",
    "theme", "then", "theory", "there", "they", "thing", "this", "thought",
    "three", "thrive", "throw", "thumb", "thunder", "ticket", "tide", "tiger",
    "tilt", "timber", "time", "tiny", "tip", "tired", "tissue", "title",
    "toast", "tobacco", "today", "toddler", "toe", "together", "toilet", "token",
    "tomato", "tomorrow", "tone", "tongue", "tonight", "tool", "tooth", "top",
    "topic", "topple", "torch", "tornado", "tortoise", "toss", "total", "tourist",
    "toward", "tower", "town", "toy", "track", "trade", "traffic", "tragic",
    "train", "transfer", "trap", "trash", "travel", "tray", "treat", "tree",
    "trend", "trial", "tribe", "trick", "trigger", "trim", "trip", "trophy",
    "trouble", "truck", "true", "truly", "trumpet", "trust", "truth", "try",
    "tube", "tuition", "tumble", "tuna", "tunnel", "turkey", "turn", "turtle",
    "twelve", "twenty", "twice", "twin", "twist", "two", "type", "typical",
    "ugly", "umbrella", "unable", "unaware", "uncle", "uncover", "under", "undo",
    "unfair", "unfold", "unhappy", "uniform", "unique", "unit", "universe", "unknown",
    "unlock", "until", "unusual", "unveil", "update", "upgrade", "uphold", "upon",
    "upper", "upset", "urban", "urge", "usage", "use", "used", "useful",
    "useless", "usual", "utility", "vacant", "vacuum", "vague", "valid", "valley",
    "valve", "van", "vanish", "vapor", "various", "vast", "vault", "vehicle",
    "velvet", "vendor", "venture", "venue", "verb", "verify", "version", "very",
    "vessel", "veteran", "viable", "vibrant", "vicious", "victory", "video", "view",
    "village", "vintage", "violin", "virtual", "virus", "visa", "visit", "visual",
    "vital", "vivid", "vocal", "voice", "void", "volcano", "volume", "vote",
    "voyage", "wage", "wagon", "wait", "walk", "wall", "walnut", "want",
    "warfare", "warm", "warrior", "wash", "wasp", "waste", "water", "wave",
    "way", "wealth", "weapon", "wear", "weasel", "weather", "web", "wedding",
    "weekend", "weird", "welcome", "west", "wet", "whale", "what", "wheat",
    "wheel", "when", "where", "whip", "whisper", "wide", "width", "wife",
    "wild", "will", "win", "window", "wine", "wing", "wink", "winner",
    "winter", "wire", "wisdom", "wise", "wish", "witness", "wolf", "woman",
    "wonder", "wood", "wool", "word", "work", "world", "worry", "worth",
    "wrap", "wreck", "wrestle", "wrist", "write", "wrong", "yard", "year",
    "yellow", "you", "young", "youth", "zebra", "zero", "zone", "zoo",
]


def _generate_mnemonic(strength: int = 128) -> str:
    """
    Generate a BIP39-compatible mnemonic seed phrase.
    
    Args:
        strength: Entropy strength in bits (128, 160, 192, 224, 256)
                  128 bits = 12 words, 256 bits = 24 words
    
    Returns:
        Space-separated mnemonic seed phrase
    """
    # Generate random entropy
    entropy_bytes = secrets.token_bytes(strength // 8)
    entropy_int = int.from_bytes(entropy_bytes, 'big')
    
    # Calculate checksum
    checksum_bits = strength // 32
    hash_bytes = hashlib.sha256(entropy_bytes).digest()
    checksum = int.from_bytes(hash_bytes, 'big') >> (256 - checksum_bits)
    
    # Combine entropy and checksum
    combined = (entropy_int << checksum_bits) | checksum
    total_bits = strength + checksum_bits
    
    # Convert to words
    words = []
    for i in range(total_bits // 11):
        word_index = (combined >> (total_bits - 11 - (i * 11))) & 0x7FF
        words.append(BIP39_WORDLIST[word_index])  # 2048-word list == 2^11, 11-bit index maps exactly (full entropy, valid BIP39)
    
    return ' '.join(words)


def _mnemonic_to_seed(mnemonic: str, passphrase: str = "") -> bytes:
    """
    Convert a BIP39 mnemonic to a seed using PBKDF2.
    
    Args:
        mnemonic: Space-separated seed phrase
        passphrase: Optional passphrase for additional security
    
    Returns:
        64-byte seed
    """
    salt = f"mnemonic{passphrase}".encode()
    mnemonic_bytes = mnemonic.encode('utf-8')
    
    # PBKDF2-HMAC-SHA512 with 2048 iterations (BIP39 standard)
    if CRYPTO_AVAILABLE:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA512(),
            length=64,
            salt=salt,
            iterations=2048,
            backend=default_backend(),
        )
        return kdf.derive(mnemonic_bytes)
    else:
        # Fallback: simple hash-based derivation (less secure, for testing only)
        return hashlib.sha512(salt + mnemonic_bytes).digest()


def _seed_to_ed25519_keypair(seed: bytes) -> tuple[bytes, bytes]:
    """
    Derive Ed25519 keypair from seed.
    
    Args:
        seed: 64-byte seed from mnemonic
    
    Returns:
        Tuple of (private_key, public_key) as bytes
    """
    if NACL_AVAILABLE:
        # Use PyNaCl for Ed25519
        signing_key = nacl_signing.SigningKey(seed[:32])
        return bytes(signing_key), bytes(signing_key.verify_key)
    
    elif ED25519_AVAILABLE:
        # Use ed25519 library
        signing_key = ed25519.SigningKey(seed[:32])
        return signing_key.to_bytes(), signing_key.get_verifying_key().to_bytes()
    
    else:
        # Fallback: use cryptography library or simple derivation
        # In production, require one of the above libraries
        # For now, use a simple deterministic derivation
        private_key = hashlib.sha256(seed).digest()
        public_key = hashlib.sha256(private_key).digest()
        return private_key, public_key


def _bytes_to_hex(data: bytes) -> str:
    """Convert bytes to hex string."""
    return data.hex()


def _hex_to_bytes(hex_str: str) -> bytes:
    """Convert hex string to bytes."""
    return bytes.fromhex(hex_str)


def _derive_wallet_address(public_key: bytes) -> str:
    """
    Derive a RustChain wallet address from a public key.
    
    Args:
        public_key: Ed25519 public key bytes
    
    Returns:
        Wallet address string (RTC address format)
    """
    # Hash the public key to create address
    address_hash = hashlib.sha256(public_key).digest()
    # Prefix with "RTC" and encode as hex
    return "RTC" + address_hash[:20].hex()


def _encrypt_data(data: str, password: str) -> str:
    """
    Encrypt data using Fernet (AES-128-CBC).
    
    Args:
        data: Plaintext data to encrypt
        password: Password for encryption
    
    Returns:
        Base64-encoded encrypted data
    """
    if not CRYPTO_AVAILABLE:
        # Fallback: simple XOR encryption (NOT SECURE - for testing only)
        key = hashlib.sha256(password.encode()).digest()
        data_bytes = data.encode()
        encrypted = bytes(a ^ b for a, b in zip(data_bytes, (key * ((len(data_bytes) // len(key)) + 1))[:len(data_bytes)]))
        return base64.b64encode(encrypted).decode()
    
    # Derive key from password
    salt = secrets.token_bytes(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend(),
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    fernet = Fernet(key)
    
    encrypted = fernet.encrypt(data.encode())
    # Prepend salt for decryption
    return base64.b64encode(salt + encrypted).decode()


def _decrypt_data(encrypted_data: str, password: str) -> str:
    """
    Decrypt data encrypted with _encrypt_data.
    
    Args:
        encrypted_data: Base64-encoded encrypted data
        password: Password for decryption
    
    Returns:
        Decrypted plaintext
    """
    if not CRYPTO_AVAILABLE:
        # Fallback: simple XOR decryption
        key = hashlib.sha256(password.encode()).digest()
        data_bytes = base64.b64decode(encrypted_data.encode())
        decrypted = bytes(a ^ b for a, b in zip(data_bytes, (key * ((len(data_bytes) // len(key)) + 1))[:len(data_bytes)]))
        return decrypted.decode()
    
    decoded = base64.b64decode(encrypted_data.encode())
    salt = decoded[:16]
    encrypted = decoded[16:]
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend(),
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    fernet = Fernet(key)
    
    return fernet.decrypt(encrypted).decode()


def sign_message(message: bytes, private_key_hex: str) -> str:
    """
    Sign a message using Ed25519.
    
    Args:
        message: Message bytes to sign
        private_key_hex: Private key as hex string
    
    Returns:
        Hex-encoded signature
    """
    private_key = _hex_to_bytes(private_key_hex)
    
    if NACL_AVAILABLE:
        signing_key = nacl_signing.SigningKey(private_key)
        signed = signing_key.sign(message)
        return signed.signature.hex()
    
    elif ED25519_AVAILABLE:
        signing_key = ed25519.SigningKey(private_key)
        signature = signing_key.sign(message)
        return signature.hex()
    
    else:
        # Fallback: create a deterministic signature (NOT SECURE - for testing only)
        # In production, require nacl or ed25519 library
        return hashlib.sha256(private_key + message).hexdigest()


def verify_signature(message: bytes, signature_hex: str, public_key_hex: str) -> bool:
    """
    Verify an Ed25519 signature.
    
    Args:
        message: Original message bytes
        signature_hex: Hex-encoded signature
        public_key_hex: Hex-encoded public key
    
    Returns:
        True if signature is valid
    """
    public_key = _hex_to_bytes(public_key_hex)
    signature = _hex_to_bytes(signature_hex)
    
    if NACL_AVAILABLE:
        try:
            verify_key = nacl_signing.VerifyKey(public_key)
            verify_key.verify(message, signature)
            return True
        except Exception:  # noqa: BLE001
            return False
    
    elif ED25519_AVAILABLE:
        try:
            verify_key = ed25519.VerifyingKey(public_key)
            verify_key.verify(signature, message)
            return True
        except Exception:  # noqa: BLE001
            return False
    
    else:
        # Fallback: cannot verify without proper library
        return False


# ═══════════════════════════════════════════════════════════════
# Keystore Management
# ═══════════════════════════════════════════════════════════════

def get_keystore_path() -> Path:
    """Get the keystore directory path (~/.rustchain/mcp_wallets/)."""
    return Path.home() / ".rustchain" / "mcp_wallets"


def ensure_keystore_exists() -> Path:
    """Ensure the keystore directory exists, create if necessary."""
    keystore_path = get_keystore_path()
    keystore_path.mkdir(parents=True, exist_ok=True)
    # Set restrictive permissions (owner read/write/execute only)
    os.chmod(keystore_path, 0o700)
    return keystore_path


def create_wallet(agent_name: str, password: str = "") -> dict[str, Any]:
    """
    Create a new Ed25519 wallet with BIP39 seed phrase.
    
    Args:
        agent_name: Name for the wallet (will be slugified)
        password: Optional password to encrypt the keystore
    
    Returns:
        Dictionary with wallet_id, address, and public_key
        (NEVER returns private_key or mnemonic in production)
    """
    # Generate mnemonic
    mnemonic = _generate_mnemonic(strength=128)  # 12 words
    
    # Derive seed and keypair
    seed = _mnemonic_to_seed(mnemonic)
    private_key, public_key = _seed_to_ed25519_keypair(seed)
    
    # Derive wallet address
    address = _derive_wallet_address(public_key)
    
    # Create wallet ID from agent name (slugify: lowercase, replace spaces/underscores/special chars with hyphens)
    import re
    wallet_id = re.sub(r'[^a-z0-9]+', '-', agent_name.lower()).strip('-')
    
    # Store in keystore (encrypted)
    keystore_path = ensure_keystore_exists()
    wallet_file = keystore_path / f"{wallet_id}.json"
    
    keystore_data = {
        "version": 1,
        "wallet_id": wallet_id,
        "address": address,
        "public_key": _bytes_to_hex(public_key),
        "encrypted_private_key": _encrypt_data(_bytes_to_hex(private_key), password or wallet_id),
        "encrypted_mnemonic": _encrypt_data(mnemonic, password or wallet_id),
        "created_at": int(os.path.getmtime(keystore_path)) if wallet_file.exists() else int(__import__('time').time()),
    }
    
    # Write keystore file
    with open(wallet_file, 'w') as f:
        json.dump(keystore_data, f, indent=2)
    os.chmod(wallet_file, 0o600)
    
    # Return only public information
    return {
        "wallet_id": wallet_id,
        "address": address,
        "public_key": keystore_data["public_key"],
        "message": f"Wallet created for '{agent_name}'. Store your seed phrase securely!",
        # NOTE: In a real scenario, the mnemonic would be shown ONCE to the user
        # and never stored. Here we omit it for security.
    }


def load_wallet(wallet_id: str, password: str = "") -> dict[str, Any] | None:
    """
    Load a wallet from the keystore.
    
    Args:
        wallet_id: Wallet ID to load
        password: Password to decrypt the keystore
    
    Returns:
        Wallet data including private_key and mnemonic if password is correct,
        None if wallet not found or password incorrect
    """
    keystore_path = get_keystore_path()
    wallet_file = keystore_path / f"{wallet_id}.json"
    
    if not wallet_file.exists():
        return None
    
    try:
        with open(wallet_file, 'r') as f:
            keystore_data = json.load(f)
        
        # Decrypt private key and mnemonic
        private_key_hex = _decrypt_data(keystore_data["encrypted_private_key"], password or wallet_id)
        mnemonic = _decrypt_data(keystore_data["encrypted_mnemonic"], password or wallet_id)
        
        return {
            "wallet_id": keystore_data["wallet_id"],
            "address": keystore_data["address"],
            "public_key": keystore_data["public_key"],
            "private_key": private_key_hex,
            "mnemonic": mnemonic,
            "created_at": keystore_data.get("created_at"),
        }
    except Exception:  # noqa: BLE001
        # Decryption failed (wrong password or corrupted data)
        return None


def list_wallets() -> list[dict[str, Any]]:
    """
    List all wallets in the local keystore.
    
    Returns:
        List of wallet info dictionaries (wallet_id, address, created_at)
    """
    keystore_path = get_keystore_path()
    wallets = []
    
    if not keystore_path.exists():
        return wallets
    
    for wallet_file in keystore_path.glob("*.json"):
        try:
            with open(wallet_file, 'r') as f:
                keystore_data = json.load(f)
            wallets.append({
                "wallet_id": keystore_data["wallet_id"],
                "address": keystore_data["address"],
                "created_at": keystore_data.get("created_at"),
            })
        except Exception:  # noqa: BLE001,S112
            continue
    
    return wallets


def export_keystore(password: str = "") -> dict[str, Any]:
    """
    Export the entire keystore as encrypted JSON.
    
    Args:
        password: Password to encrypt the export
    
    Returns:
        Encrypted keystore JSON (base64-encoded)
    """
    keystore_path = get_keystore_path()
    wallets = []
    
    if keystore_path.exists():
        for wallet_file in keystore_path.glob("*.json"):
            try:
                with open(wallet_file, 'r') as f:
                    wallet_data = json.load(f)
                wallets.append(wallet_data)
            except Exception:  # noqa: BLE001,S112
                continue
    
    export_data = {
        "version": 1,
        "exported_at": int(__import__('time').time()),
        "wallets": wallets,
    }
    
    export_json = json.dumps(export_data)
    encrypted_export = _encrypt_data(export_json, password or "rustchain-mcp-export")
    
    return {
        "encrypted_keystore": encrypted_export,
        "wallet_count": len(wallets),
        "message": f"Exported {len(wallets)} wallet(s). Store this encrypted backup securely!",
    }


def import_wallet(
    source: str,
    wallet_id: str = "",
    password: str = "",
) -> dict[str, Any]:
    """
    Import a wallet from seed phrase or keystore JSON.

    Args:
        source: Either a BIP39 seed phrase (space-separated words) or
                encrypted keystore JSON string
        wallet_id: Desired wallet ID (optional, auto-generated if not provided)
        password: Password for encrypted keystore or seed phrase

    Returns:
        Imported wallet info (wallet_id, address)
    """
    # First try to parse as JSON (encrypted keystore export)
    try:
        imported_data = json.loads(source)
        
        # Handle single wallet or wallet array
        wallets_to_import = imported_data.get("wallets", [imported_data])
        
        imported_count = 0
        for wallet_data in wallets_to_import:
            target_id = wallet_id or wallet_data.get("wallet_id", f"imported-{__import__('time').time()}")
            
            keystore_path = ensure_keystore_exists()
            wallet_file = keystore_path / f"{target_id}.json"
            
            # Re-encrypt with new password
            keystore_data = {
                "version": 1,
                "wallet_id": target_id,
                "address": wallet_data["address"],
                "public_key": wallet_data.get("public_key", ""),
                "encrypted_private_key": _encrypt_data(
                    wallet_data.get("encrypted_private_key", ""),
                    password or target_id,
                ),
                "encrypted_mnemonic": _encrypt_data(
                    wallet_data.get("encrypted_mnemonic", ""),
                    password or target_id,
                ),
                "created_at": int(__import__('time').time()),
                "imported_from": "keystore",
            }
            
            with open(wallet_file, 'w') as f:
                json.dump(keystore_data, f, indent=2)
            os.chmod(wallet_file, 0o600)
            imported_count += 1
        
        return {
            "wallets_imported": imported_count,
            "message": f"Successfully imported {imported_count} wallet(s)",
        }
    except json.JSONDecodeError:
        pass
    
    # If JSON parsing failed, try seed phrase import
    words = source.strip().split()
    is_seed_phrase = 12 <= len(words) <= 24 and all(w in BIP39_WORDLIST for w in words)

    if is_seed_phrase:
        # Import from seed phrase
        mnemonic = source.strip()
        seed = _mnemonic_to_seed(mnemonic)
        private_key, public_key = _seed_to_ed25519_keypair(seed)
        address = _derive_wallet_address(public_key)

        # Generate wallet_id if not provided
        if not wallet_id:
            wallet_id = f"imported-{address[:8]}"

        # Store in keystore
        keystore_path = ensure_keystore_exists()
        wallet_file = keystore_path / f"{wallet_id}.json"

        keystore_data = {
            "version": 1,
            "wallet_id": wallet_id,
            "address": address,
            "public_key": _bytes_to_hex(public_key),
            "encrypted_private_key": _encrypt_data(_bytes_to_hex(private_key), password or wallet_id),
            "encrypted_mnemonic": _encrypt_data(mnemonic, password or wallet_id),
            "created_at": int(__import__('time').time()),
            "imported_from": "seed_phrase",
        }

        with open(wallet_file, 'w') as f:
            json.dump(keystore_data, f, indent=2)
        os.chmod(wallet_file, 0o600)

        return {
            "wallet_id": wallet_id,
            "address": address,
            "message": f"Wallet imported from seed phrase. Address: {address}",
        }
    
    return {
        "error": "Invalid input: not a valid seed phrase or keystore JSON",
    }
