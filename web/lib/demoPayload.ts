import type { ApplicantPayload } from "./types";

export const demoPayload: ApplicantPayload = {
  target_regions: ["HK", "SG"],
  target_cycle: "2027-fall",
  target_degree: "taught_master",
  discipline_interests: ["computer_science", "artificial_intelligence", "data_science"],
  raw_interest_text:
    "我主要关注计算机、人工智能、数据科学、机器学习和大数据方向。",
  education: {
    school: "",
    school_tier: "985",
    degree: "Bachelor",
    major: "人工智能",
    gpa: 84.5,
    gpa_scale: "100",
    ranking_percentile: 18,
    evidence_level: "SELF_REPORTED"
  },
  language: {
    test: "IELTS",
    overall: 6.5,
    writing: 6,
    speaking: 6.5,
    reading: 7,
    listening: 6.5,
    evidence_level: "SELF_REPORTED"
  },
  experiences: [
    {
      type: "internship",
      title: "Product Data Analyst Intern",
      organization: "Fintech SaaS Startup",
      months: 4,
      role: "built retention dashboard and cohort analysis",
      outcomes: ["reduced weekly reporting time by 40%", "identified churn signal in onboarding funnel"],
      tools: ["SQL", "Python", "statistics", "Tableau"],
      evidence_level: "SELF_REPORTED"
    },
    {
      type: "project",
      title: "Course Recommender System",
      organization: "University Capstone",
      months: 5,
      role: "implemented ranking features and evaluation script",
      outcomes: ["achieved 0.71 offline NDCG on synthetic evaluation data"],
      tools: ["Python", "machine learning", "database"],
      evidence_level: "USER_CONFIRMED"
    }
  ],
  budget_hkd: 420000,
  career_goal: "希望进入跨境科技公司做产品数据分析。",
  risk_flags: []
};
