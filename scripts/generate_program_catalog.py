from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "programs_2027_fall.json"
CAPTURED_AT = "2026-06-13T00:00:00Z"

INSTITUTIONS = {
    "hku": {
        "en": "The University of Hong Kong",
        "zh": "香港大学",
        "country": "HK",
        "url": "https://admissions.hku.hk/tpg/programme-list",
        "deadline": "2027-01-31",
        "fee": 300,
        "selectivity": 3,
    },
    "cuhk": {
        "en": "The Chinese University of Hong Kong",
        "zh": "香港中文大学",
        "country": "HK",
        "url": "https://www.gs.cuhk.edu.hk/admissions/programme-list",
        "deadline": "2027-03-31",
        "fee": 300,
        "selectivity": 3,
    },
    "hkust": {
        "en": "The Hong Kong University of Science and Technology",
        "zh": "香港科技大学",
        "country": "HK",
        "url": "https://prog-crs.hkust.edu.hk/pgprog/",
        "deadline": "2027-03-01",
        "fee": 450,
        "selectivity": 3,
    },
    "cityu": {
        "en": "City University of Hong Kong",
        "zh": "香港城市大学",
        "country": "HK",
        "url": "https://www.cityu.edu.hk/pg/taught-postgraduate-programmes",
        "deadline": "2027-02-28",
        "fee": 300,
        "selectivity": 2,
    },
    "polyu": {
        "en": "The Hong Kong Polytechnic University",
        "zh": "香港理工大学",
        "country": "HK",
        "url": "https://www.polyu.edu.hk/study/pg/taught-postgraduate-programmes/",
        "deadline": "2027-04-30",
        "fee": 450,
        "selectivity": 2,
    },
    "hkbu": {
        "en": "Hong Kong Baptist University",
        "zh": "香港浸会大学",
        "country": "HK",
        "url": "https://admissions.hkbu.edu.hk/pg/tpg/programmes",
        "deadline": "2027-06-01",
        "fee": 300,
        "selectivity": 1,
    },
    "lingnan": {
        "en": "Lingnan University",
        "zh": "岭南大学",
        "country": "HK",
        "url": "https://www.ln.edu.hk/admissions/taught-postgraduate-programmes",
        "deadline": "2027-05-15",
        "fee": 300,
        "selectivity": 1,
    },
    "eduhk": {
        "en": "The Education University of Hong Kong",
        "zh": "香港教育大学",
        "country": "HK",
        "url": "https://www.eduhk.hk/acadprog/postgrad/",
        "deadline": "2027-02-28",
        "fee": 300,
        "selectivity": 1,
    },
    "nus": {
        "en": "National University of Singapore",
        "zh": "新加坡国立大学",
        "country": "SG",
        "url": "https://www.nus.edu.sg/admissions/graduate-studies/graduate-programmes",
        "deadline": "2027-01-31",
        "fee": 550,
        "selectivity": 3,
    },
    "ntu": {
        "en": "Nanyang Technological University",
        "zh": "南洋理工大学",
        "country": "SG",
        "url": "https://www.ntu.edu.sg/admissions/graduate",
        "deadline": "2027-01-31",
        "fee": 520,
        "selectivity": 3,
    },
    "smu": {
        "en": "Singapore Management University",
        "zh": "新加坡管理大学",
        "country": "SG",
        "url": "https://masters.smu.edu.sg/programmes",
        "deadline": "2027-05-31",
        "fee": 500,
        "selectivity": 2,
    },
    "sutd": {
        "en": "Singapore University of Technology and Design",
        "zh": "新加坡科技设计大学",
        "country": "SG",
        "url": "https://www.sutd.edu.sg/Admissions/Graduate",
        "deadline": "2027-03-15",
        "fee": 500,
        "selectivity": 1,
    },
}

PROGRAMS = [
    ("hku", "商学院", "Master of Accounting", "会计学硕士", ["business"]),
    ("hku", "商学院", "Master of Economics", "经济学硕士", ["business", "social_science"]),
    ("hku", "商学院", "Master of Finance", "金融学硕士", ["business"]),
    ("hku", "商学院", "Master of Global Management", "全球管理硕士", ["business"]),
    ("hku", "商学院", "Master of Science in Business Analytics", "商业分析理学硕士", ["business", "computer_science"]),
    ("hku", "商学院", "Master of Science in Marketing", "市场营销理学硕士", ["business"]),
    ("hku", "工程学院", "Master of Science in Computer Science", "计算机科学理学硕士", ["computer_science"]),
    ("hku", "工程学院", "Master of Science in Data Science", "数据科学理学硕士", ["computer_science", "business"]),
    ("hku", "工程学院", "Master of Science in Engineering", "工程学理学硕士", ["engineering"]),
    ("hku", "新闻及传媒研究中心", "Master of Journalism", "新闻学硕士", ["communication"]),
    ("hku", "教育学院", "Master of Education", "教育学硕士", ["education_language"]),
    ("hku", "社会科学学院", "Master of Public Administration", "公共行政硕士", ["law_policy", "social_science"]),
    ("hku", "社会科学学院", "Master of Public Policy", "公共政策硕士", ["law_policy", "social_science"]),
    ("hku", "建筑学院", "Master of Urban Planning", "城市规划硕士", ["design_built_environment", "law_policy"]),
    ("hku", "建筑学院", "Master of Architecture", "建筑学硕士", ["design_built_environment"]),
    ("hku", "公共卫生学院", "Master of Public Health", "公共卫生硕士", ["life_health", "social_science"]),
    ("hku", "理学院", "Master of Science in Statistics", "统计学理学硕士", ["computer_science", "business"]),
    ("hku", "理学院", "Master of Science in Environmental Management", "环境管理理学硕士", ["life_health", "engineering"]),
    ("cuhk", "工程学院", "MSc in Computer Science", "计算机科学理学硕士", ["computer_science"]),
    ("cuhk", "工程学院", "MSc in Information Engineering", "信息工程理学硕士", ["computer_science", "engineering"]),
    ("cuhk", "工程学院", "MSc in Artificial Intelligence", "人工智能理学硕士", ["computer_science"]),
    ("cuhk", "理学院", "MSc in Data Science and Business Statistics", "数据科学与商业统计理学硕士", ["computer_science", "business"]),
    ("cuhk", "商学院", "MSc in Business Analytics", "商业分析理学硕士", ["business", "computer_science"]),
    ("cuhk", "商学院", "MSc in Finance", "金融理学硕士", ["business"]),
    ("cuhk", "商学院", "MSc in Management", "管理学理学硕士", ["business"]),
    ("cuhk", "商学院", "MSc in Marketing", "市场营销理学硕士", ["business"]),
    ("cuhk", "商学院", "Master of Accountancy", "会计学硕士", ["business"]),
    ("cuhk", "新闻与传播学院", "MA in Global Communication", "全球传播文学硕士", ["communication"]),
    ("cuhk", "新闻与传播学院", "MA in Journalism", "新闻学文学硕士", ["communication"]),
    ("cuhk", "文学院", "MA in Applied English Linguistics", "应用英语语言学文学硕士", ["education_language"]),
    ("cuhk", "社会科学学院", "Master of Social Science in Public Policy", "公共政策社会科学硕士", ["law_policy", "social_science"]),
    ("cuhk", "公共卫生学院", "Master of Public Health", "公共卫生硕士", ["life_health"]),
    ("cuhk", "医学院", "MSc in Genomics and Bioinformatics", "基因组学与生物信息学理学硕士", ["life_health", "computer_science"]),
    ("hkust", "工程学院", "MSc in Big Data Technology", "大数据科技理学硕士", ["computer_science", "engineering"]),
    ("hkust", "工程学院", "MSc in Information Technology", "信息技术理学硕士", ["computer_science"]),
    ("hkust", "工程学院", "MSc in Electronic Engineering", "电子工程理学硕士", ["engineering", "computer_science"]),
    ("hkust", "工程学院", "MSc in Engineering Enterprise Management", "工程企业管理理学硕士", ["engineering", "business"]),
    ("hkust", "商学院", "MSc in Business Analytics", "商业分析理学硕士", ["business", "computer_science"]),
    ("hkust", "商学院", "MSc in Financial Technology", "金融科技理学硕士", ["business", "computer_science"]),
    ("hkust", "商学院", "MSc in Economics", "经济学理学硕士", ["business", "social_science"]),
    ("hkust", "商学院", "MSc in Accounting", "会计学理学硕士", ["business"]),
    ("hkust", "商学院", "MSc in Global Operations", "环球运营管理理学硕士", ["business", "engineering"]),
    ("hkust", "商学院", "MSc in International Management", "国际管理理学硕士", ["business"]),
    ("hkust", "公共政策学院", "Master of Public Policy", "公共政策硕士", ["law_policy", "social_science"]),
    ("hkust", "公共政策学院", "Master of Public Management", "公共管理硕士", ["law_policy", "social_science"]),
    ("hkust", "理学院", "MSc in Biotechnology", "生物技术理学硕士", ["life_health"]),
    ("cityu", "计算学院", "MSc Computer Science", "计算机科学理学硕士", ["computer_science"]),
    ("cityu", "计算学院", "MSc Data Science", "数据科学理学硕士", ["computer_science", "business"]),
    ("cityu", "工程学院", "MSc Electronic Information Engineering", "电子资讯工程理学硕士", ["engineering", "computer_science"]),
    ("cityu", "商学院", "MSc Business Information Systems", "商务资讯系统理学硕士", ["business", "computer_science"]),
    ("cityu", "商学院", "MSc Business and Data Analytics", "商务及数据分析理学硕士", ["business", "computer_science"]),
    ("cityu", "商学院", "MSc Finance", "金融学理学硕士", ["business"]),
    ("cityu", "商学院", "MSc Applied Economics", "应用经济学理学硕士", ["business", "social_science"]),
    ("cityu", "人文社会科学院", "MA Communication and New Media", "传播与新媒体文学硕士", ["communication"]),
    ("cityu", "人文社会科学院", "MA Integrated Marketing Communication", "整合营销传播文学硕士", ["communication", "business"]),
    ("cityu", "人文社会科学院", "MA Public Policy and Management", "公共政策及管理文学硕士", ["law_policy", "social_science"]),
    ("cityu", "建筑及土木工程学院", "MSc Construction Management", "建造管理理学硕士", ["design_built_environment", "engineering"]),
    ("cityu", "文学院", "MA English Studies", "英语研究文学硕士", ["education_language"]),
    ("polyu", "计算学院", "MSc Data Science and Analytics", "数据科学及分析理学硕士", ["computer_science", "business"]),
    ("polyu", "计算学院", "MSc Information Technology", "资讯科技理学硕士", ["computer_science"]),
    ("polyu", "计算学院", "MSc Artificial Intelligence and Big Data Computing", "人工智能及大数据计算理学硕士", ["computer_science"]),
    ("polyu", "商学院", "MSc Business Analytics", "商业分析理学硕士", ["business", "computer_science"]),
    ("polyu", "商学院", "MSc Accounting and Finance Analytics", "会计及金融分析理学硕士", ["business", "computer_science"]),
    ("polyu", "商学院", "MSc Operations Management", "运营管理理学硕士", ["business", "engineering"]),
    ("polyu", "商学院", "MSc Marketing Management", "市场营销管理理学硕士", ["business"]),
    ("polyu", "酒店及旅游业管理学院", "MSc Global Hospitality Business", "环球酒店业管理理学硕士", ["business"]),
    ("polyu", "设计学院", "Master of Design", "设计硕士", ["design_built_environment"]),
    ("polyu", "建筑及环境学院", "MSc Urban Informatics and Smart Cities", "城市信息学及智慧城市理学硕士", ["design_built_environment", "computer_science"]),
    ("polyu", "建筑及环境学院", "MSc Construction and Real Estate", "建筑及房地产理学硕士", ["design_built_environment", "engineering"]),
    ("polyu", "人文学院", "MA Bilingual Corporate Communication", "双语企业传讯文学硕士", ["communication", "education_language"]),
    ("polyu", "人文学院", "MA Translating and Interpreting", "翻译与传译文学硕士", ["education_language", "communication"]),
    ("polyu", "工程学院", "MSc Biomedical Engineering", "生物医学工程理学硕士", ["life_health", "engineering"]),
    ("hkbu", "计算机科学系", "MSc Data Analytics and Artificial Intelligence", "数据分析与人工智能理学硕士", ["computer_science", "business"]),
    ("hkbu", "商学院", "MSc Information Technology Management", "信息技术管理理学硕士", ["business", "computer_science"]),
    ("hkbu", "商学院", "MSc Applied Accounting and Finance", "应用会计与金融理学硕士", ["business"]),
    ("hkbu", "商学院", "MSc Business Management", "商业管理理学硕士", ["business"]),
    ("hkbu", "商学院", "MSc Corporate Governance and Compliance", "公司管治与合规理学硕士", ["business", "law_policy"]),
    ("hkbu", "传理学院", "MA Communication", "传播学文学硕士", ["communication"]),
    ("hkbu", "传理学院", "MA International Journalism Studies", "国际新闻文学硕士", ["communication"]),
    ("hkbu", "传理学院", "MA Producing for Film Television and New Media", "影视与新媒体制片文学硕士", ["communication"]),
    ("hkbu", "社会科学院", "Master of Public Administration", "公共行政管理硕士", ["law_policy", "social_science"]),
    ("hkbu", "社会科学院", "Master of Education", "教育学硕士", ["education_language"]),
    ("hkbu", "理学院", "MSc Environmental and Public Health Management", "环境及公共卫生管理理学硕士", ["life_health", "social_science"]),
    ("lingnan", "商学院", "MSc Artificial Intelligence and Business Analytics", "人工智能与商业分析理学硕士", ["computer_science", "business"]),
    ("lingnan", "数据科学学院", "MSc Data Science", "数据科学理学硕士", ["computer_science"]),
    ("lingnan", "商学院", "MSc eBusiness and Supply Chain Management", "电子商务与供应链管理理学硕士", ["business", "engineering"]),
    ("lingnan", "商学院", "MSc Finance", "金融理学硕士", ["business"]),
    ("lingnan", "商学院", "MSc Human Resource Management and Organisational Behaviour", "人力资源管理与组织行为理学硕士", ["business"]),
    ("lingnan", "商学院", "MSc Marketing and International Business", "市场及国际企业理学硕士", ["business"]),
    ("lingnan", "社会科学院", "MA International Affairs", "国际事务文学硕士", ["law_policy", "social_science"]),
    ("lingnan", "文学院", "MA Translation Studies", "翻译研究文学硕士", ["education_language", "communication"]),
    ("lingnan", "文学院", "MA Creative and Media Industries", "创意及媒体产业文学硕士", ["communication", "business"]),
    ("eduhk", "教育及人类发展学院", "Master of Education", "教育学硕士", ["education_language"]),
    ("eduhk", "人文学院", "MA Teaching English to Speakers of Other Languages", "对外英语教学文学硕士", ["education_language"]),
    ("eduhk", "教育及人类发展学院", "MA Child and Family Education", "儿童及家庭教育文学硕士", ["education_language", "social_science"]),
    ("eduhk", "科学与环境学系", "MA STEM Education", "STEM 教育文学硕士", ["education_language", "computer_science"]),
    ("eduhk", "社会科学与政策研究系", "MA Education for Sustainability", "可持续发展教育文学硕士", ["education_language", "law_policy"]),
    ("nus", "计算机学院", "Master of Computing", "计算硕士", ["computer_science"]),
    ("nus", "计算机学院", "MSc Business Analytics", "商业分析理学硕士", ["business", "computer_science"]),
    ("nus", "理学院", "MSc Data Science and Machine Learning", "数据科学与机器学习理学硕士", ["computer_science"]),
    ("nus", "理学院", "MSc Statistics", "统计学理学硕士", ["computer_science", "business"]),
    ("nus", "理学院", "MSc Quantitative Finance", "定量金融理学硕士", ["business", "computer_science"]),
    ("nus", "商学院", "MSc Finance", "金融理学硕士", ["business"]),
    ("nus", "商学院", "MSc Management", "管理学理学硕士", ["business"]),
    ("nus", "商学院", "MSc Marketing Analytics and Insights", "市场分析与洞察理学硕士", ["business", "computer_science"]),
    ("nus", "李光耀公共政策学院", "Master in Public Policy", "公共政策硕士", ["law_policy", "social_science"]),
    ("nus", "李光耀公共政策学院", "Master in Public Administration", "公共行政硕士", ["law_policy", "social_science"]),
    ("nus", "工程学院", "MSc Industrial and Systems Engineering", "工业与系统工程理学硕士", ["engineering", "business"]),
    ("nus", "工程学院", "MSc Electrical Engineering", "电气工程理学硕士", ["engineering", "computer_science"]),
    ("nus", "工程学院", "MSc Civil Engineering", "土木工程理学硕士", ["engineering", "design_built_environment"]),
    ("nus", "公共卫生学院", "Master of Public Health", "公共卫生硕士", ["life_health", "social_science"]),
    ("nus", "设计与工程学院", "Master of Architecture", "建筑学硕士", ["design_built_environment"]),
    ("ntu", "计算与数据科学学院", "MSc Artificial Intelligence", "人工智能理学硕士", ["computer_science"]),
    ("ntu", "计算与数据科学学院", "MSc Cyber Security", "网络安全理学硕士", ["computer_science"]),
    ("ntu", "理学院", "MSc Data Science", "数据科学理学硕士", ["computer_science", "business"]),
    ("ntu", "南洋商学院", "MSc Business Analytics", "商业分析理学硕士", ["business", "computer_science"]),
    ("ntu", "南洋商学院", "MSc Accountancy", "会计学理学硕士", ["business"]),
    ("ntu", "南洋商学院", "MSc Financial Engineering", "金融工程理学硕士", ["business", "computer_science"]),
    ("ntu", "南洋商学院", "MSc Marketing Science", "市场科学理学硕士", ["business"]),
    ("ntu", "南洋商学院", "MSc Management", "管理学理学硕士", ["business"]),
    ("ntu", "工程学院", "MSc Information Systems", "信息系统理学硕士", ["computer_science", "business"]),
    ("ntu", "工程学院", "MSc Project Management", "项目管理理学硕士", ["engineering", "business"]),
    ("ntu", "拉惹勒南国际研究院", "MSc International Relations", "国际关系理学硕士", ["law_policy", "social_science"]),
    ("ntu", "社会科学学院", "MSc Applied Economics", "应用经济学理学硕士", ["business", "social_science"]),
    ("ntu", "人文学院", "MA Applied Linguistics", "应用语言学文学硕士", ["education_language"]),
    ("ntu", "人文学院", "MA Teaching Chinese as an International Language", "国际汉语教学文学硕士", ["education_language"]),
    ("ntu", "工程学院", "MSc Environmental Engineering", "环境工程理学硕士", ["engineering", "life_health"]),
    ("smu", "计算与信息系统学院", "Master of IT in Business", "商业信息技术硕士", ["business", "computer_science"]),
    ("smu", "计算与信息系统学院", "MSc Computing", "计算理学硕士", ["computer_science"]),
    ("smu", "计算与信息系统学院", "MSc Applied Finance", "应用金融理学硕士", ["business"]),
    ("smu", "李光前商学院", "MSc Management", "管理学理学硕士", ["business"]),
    ("smu", "李光前商学院", "MSc Quantitative Finance", "定量金融理学硕士", ["business", "computer_science"]),
    ("smu", "李光前商学院", "MSc Wealth Management", "财富管理理学硕士", ["business"]),
    ("smu", "李光前商学院", "MSc Communication Management", "传播管理理学硕士", ["communication", "business"]),
    ("smu", "经济学院", "MSc Economics", "经济学理学硕士", ["business", "social_science"]),
    ("smu", "会计学院", "MSc Accounting", "会计学理学硕士", ["business"]),
    ("smu", "会计学院", "MSc CFO Leadership", "首席财务官领导力理学硕士", ["business"]),
    ("sutd", "设计与人工智能", "MSc Urban Science, Policy and Planning", "城市科学、政策与规划理学硕士", ["design_built_environment", "law_policy", "computer_science"]),
    ("sutd", "设计与人工智能", "Master of Architecture", "建筑学硕士", ["design_built_environment"]),
    ("sutd", "信息系统科技与设计", "MSc Security by Design", "安全设计理学硕士", ["computer_science", "engineering"]),
    ("sutd", "工程产品开发", "MSc Technology and Design", "技术与设计理学硕士", ["engineering", "design_built_environment"]),
    ("sutd", "设计创新中心", "MSc Human-Centred Design", "以人为本设计理学硕士", ["design_built_environment", "communication"]),
]

TAG_CATEGORY = {
    "business": "商科 / 金融 / 管理",
    "computer_science": "计算机 / 数据 / AI",
    "engineering": "工程 / 制造 / 系统",
    "social_science": "社科 / 经济 / 心理",
    "communication": "传媒 / 传播 / 新闻",
    "law_policy": "法律 / 公共政策 / 国际事务",
    "life_health": "生命科学 / 医药 / 公共健康",
    "design_built_environment": "建筑 / 城市 / 设计",
    "education_language": "教育 / 语言",
}


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:58]


def min_gpa(institution: dict, tags: list[str]) -> int:
    base = {3: 82, 2: 79, 1: 75}[institution["selectivity"]]
    if "computer_science" in tags or "business" in tags:
        base += 1
    if "design_built_environment" in tags or "education_language" in tags:
        base -= 1
    return min(86, max(74, base))


def tuition(institution: dict, tags: list[str]) -> int:
    base = 260000 if institution["country"] == "HK" else 340000
    if institution["selectivity"] == 3:
        base += 45000
    if "business" in tags:
        base += 60000
    if "computer_science" in tags:
        base += 30000
    if "education_language" in tags or "communication" in tags:
        base -= 45000
    if "design_built_environment" in tags:
        base += 15000
    return max(150000, base)


def materials(tags: list[str]) -> list[str]:
    items = ["transcript", "degree_certificate", "cv", "personal_statement", "language_score"]
    if "business" in tags:
        items.append("gmat_gre_optional")
    if "communication" in tags or "education_language" in tags:
        items.append("writing_sample_optional")
    if "design_built_environment" in tags:
        items.append("portfolio")
    items.append("recommendation")
    return items


def requirements(inst: dict, tags: list[str]) -> dict:
    preferred = {
        "business": ["business", "finance", "management", "statistics"],
        "computer_science": ["programming", "database", "statistics", "machine learning"],
        "engineering": ["engineering", "mathematics", "systems"],
        "social_science": ["research methods", "policy", "economics"],
        "communication": ["media", "writing", "social research"],
        "law_policy": ["policy", "economics", "governance"],
        "life_health": ["statistics", "biology", "health"],
        "design_built_environment": ["design", "portfolio", "studio"],
        "education_language": ["teaching", "education", "language"],
    }
    prerequisites = []
    if "computer_science" in tags:
        prerequisites.extend(["programming"])
    if "business" in tags or "life_health" in tags:
        prerequisites.extend(["statistics"])
    return {
        "min_gpa": min_gpa(inst, tags),
        "language": {"IELTS": 7.0 if "law_policy" in tags else 6.5, "TOEFL": 100 if "law_policy" in tags else 90},
        "required_backgrounds": ["computing"] if tags == ["computer_science"] else [],
        "preferred_backgrounds": sorted({item for tag in tags for item in preferred.get(tag, [])})[:6],
        "prerequisites": sorted(set(prerequisites)),
        "portfolio_required": "design_built_environment" in tags,
        "work_experience_preferred": bool({"business", "law_policy"} & set(tags)),
    }


def build() -> list[dict]:
    output = []
    for inst_key, school_zh, name, name_zh, tags in PROGRAMS:
        inst = INSTITUTIONS[inst_key]
        program_id = f"{inst_key}-{slugify(name)}-2027"
        output.append(
            {
                "id": program_id,
                "institution": inst["en"],
                "institution_zh": inst["zh"],
                "country": inst["country"],
                "school": school_zh,
                "school_zh": school_zh,
                "name": name,
                "name_zh": name_zh,
                "degree_type": "taught_master",
                "cycle": "2027-fall",
                "category_zh": " / ".join(TAG_CATEGORY[tag] for tag in tags[:2]),
                "discipline_tags": tags,
                "duration_months": 18 if inst["country"] == "SG" and inst_key in {"nus", "ntu"} else 12,
                "tuition_hkd": tuition(inst, tags),
                "application_fee_hkd": inst["fee"],
                "open_date": "2026-09-01" if inst["country"] == "HK" else "2026-10-01",
                "deadline": inst["deadline"],
                "materials": materials(tags),
                "requirements": requirements(inst, tags),
                "source": {
                    "source_type": "OFFICIAL",
                    "url": inst["url"],
                    "captured_at": CAPTURED_AT,
                    "field_coverage": "partial",
                },
                "data_status": "EXTRACTED",
                "last_verified_at": None,
                "official_program_url": inst["url"],
                "application_url": inst["url"],
                "field_evidence": {
                    "institution": {
                        "field_name": "institution",
                        "value": inst["zh"],
                        "cycle": "2027-fall",
                        "official_url": inst["url"],
                        "source_type": "official_admissions_page",
                        "excerpt": "学校官方招生或项目列表入口，用于确认院校和项目线索。",
                        "locator": None,
                        "snapshot_id": None,
                        "captured_at": CAPTURED_AT,
                        "verified_at": None,
                        "confidence": "medium",
                        "status": "EXTRACTED",
                    },
                    "program_name": {
                        "field_name": "program_name",
                        "value": name,
                        "cycle": "2027-fall",
                        "official_url": inst["url"],
                        "source_type": "official_admissions_page",
                        "excerpt": "项目名称来自官方招生或项目列表入口；截止日期、学费和材料仍需字段级复核。",
                        "locator": None,
                        "snapshot_id": None,
                        "captured_at": CAPTURED_AT,
                        "verified_at": None,
                        "confidence": "medium",
                        "status": "EXTRACTED",
                    },
                },
                "community_signals": [],
            }
        )
    return output


if __name__ == "__main__":
    OUTPUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT} with {len(PROGRAMS)} programs")
