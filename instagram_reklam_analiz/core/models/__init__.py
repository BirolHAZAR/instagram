# core/models/__init__.py
# Merkezi model export dosyası
# Not: Burada sadece gerçekten mevcut model sınıfları dışa aktarılır.

from django.contrib.auth import get_user_model

User = get_user_model()

from .base import ContactMessage, DemoRequest
from .platform import Platform
from .platform_connection import PlatformConnection
from .platform_account import PlatformAccount
from .platform_sync_job import PlatformSyncJob
from .marketplace import (
    Marketplace,
    MarketplaceAccount,
    MarketplaceSyncRun,
    Product,
    ProductVariant,
    MarketplaceListing,
    MarketplaceListingMetricHistory,
    MarketplaceProductChangeHistory,
    MarketplaceProductResearch,
    MarketplaceProductResearchResult,
    MarketplaceProductResearchMetricHistory,
)
from .user_profile import (
    AccountDeletionRecord,
    DeletedAccountDeletionRecord,
    SuspendedAccountDeletionRecord,
    UserProfile,
)
from .competitor import Competitor
from .octo_task import OctoTaskRule, OctoTaskInstance, OctoTaskActionLog, OctoRuleEngineRun
from .membership import (
    MembershipPlan,
    PlanAuthorizationPolicy,
    AgencyRoleGroup,
    UserSubscription,
    ReferralCode,
    ReferralProgramSetting,
    ReferralProgramRule,
    ReferralReward,
    Organization,
    OrganizationMember,
    AgencyClient,
    PaymentMethod,
    AICreditPackage,
    AIOperationTariff,
    AICreditLedger,
    UserAICreditBalance,
    ProductResearchPackage,
    ProductResearchLedger,
    UserProductResearchBalance,
    SaaSAICreditPool,
    OpenAITokenUsageLedger,
    TavilyAPIPool,
    TavilyAPIUsageLedger,
    FeatureUsageLedger,
    BillingInfo,
    Invoice,
    Payment,
    PaymentTransaction,
)
from .celery_admin import AdminManagedCelerySchedule
from .site_settings import SiteMaintenance

from .instagram import (
    InstagramAccount,
    InstagramMedia,
    InstagramInsight,
    InstagramPostQueue,
)

# Legacy / eski kampanya modelleri hâlâ kullanılan yerler için korunur
from .campaigns import AdCampaign, AdMetric

# V2 ana reklam veri modeli
from .ad_entities import Campaign, AdGroup, Creative, Ad
from .metric_histories_v2 import (
    CampaignMetricHistory,
    AdGroupMetricHistory,
    AdMetricHistory,
    CreativeMetricHistory,
)

# Octo kampanya analiz modelleri
from .campaign_octo import CampaignOctoAnalysis, CampaignOctoRecommendation
from .health_analysis import HealthCenterAIAnalysis

# Analiz / rapor modelleri
from .analytics import AIAnalysis, ReklamAIAnaliz, Report, ScheduledReport

# Kreatif stüdyo
from .creative_studio import CreativeTemplate, CreativeProject, GeneratedContent

# Anomali / fırsat modelleri
from .anomaly_detector import AnomalyAlert, OpportunityWindow

# Bütçe optimizasyonu
from .budget_optimization import BudgetOptimizationRule, BudgetOptimizationLog

# Sistem / bildirim / log modelleri
from .error_log import SystemErrorLog
from .notification import Notification
from .communications import LifecycleEmailCampaign, LifecycleEmailDelivery, Announcement, AnnouncementDelivery
from .legal import LegalAcceptance, LegalDocument, LegalSiteSettings
from .notification_settings import NotificationPreference, ActivityLog

# Sosyal içerik
from .social import SocialPost, SocialPostMetricHistory
from .influencer import Influencer, InfluencerMetricHistory


# Control Tower snapshot / karar merkezi modelleri
from .control_tower import (
    ControlTowerSnapshot,
    ControlTowerCardSnapshot,
    ControlTowerAIAnalysis,
    ControlTowerActionItem,
    ControlTowerDecision,
)

# Ham veri snapshot modeli — admin.py burada bunu import ediyor
from .raw_data_snapshot import RawDataSnapshot

# Intelligence / geçmiş analiz modelleri
from .intelligence import (
    AudienceHistory,
    PlacementHistory,
    RawPlatformData,
    OctoScoreHistory,
    AIRecommendationHistory,
)

# Google Analytics / web analytics modelleri
try:
    from .analytics_entities import (
        AnalyticsProperty,
        AnalyticsDailyMetric,
        AnalyticsLandingPageMetric,
    )
except ImportError:
    AnalyticsProperty = None
    AnalyticsDailyMetric = None
    AnalyticsLandingPageMetric = None

__all__ = [
    "User",
    "ContactMessage",
    "DemoRequest",

    "Platform",
    "PlatformConnection",
    "PlatformAccount",
    "PlatformSyncJob",
    "Marketplace",
    "MarketplaceAccount",
    "MarketplaceSyncRun",
    "Product",
    "ProductVariant",
    "MarketplaceListing",
    "MarketplaceListingMetricHistory",
    "MarketplaceProductChangeHistory",
    "MarketplaceProductResearch",
    "MarketplaceProductResearchResult",
    "MarketplaceProductResearchMetricHistory",
    "UserProfile",
    "AccountDeletionRecord",
    "SuspendedAccountDeletionRecord",
    "DeletedAccountDeletionRecord",
    "Competitor",
    "OctoRuleEngineRun",

    "MembershipPlan",
    "PlanAuthorizationPolicy",
    "UserSubscription",
    "ReferralCode",
    "ReferralProgramSetting",
    "ReferralProgramRule",
    "ReferralReward",
    "Organization",
    "OrganizationMember",
    "AgencyClient",
    "PaymentMethod",
    "AICreditPackage",
    "AIOperationTariff",
    "AICreditLedger",
    "UserAICreditBalance",
    "ProductResearchPackage",
    "ProductResearchLedger",
    "UserProductResearchBalance",
    "SaaSAICreditPool",
    "OpenAITokenUsageLedger",
    "TavilyAPIPool",
    "TavilyAPIUsageLedger",
    "FeatureUsageLedger",
    "BillingInfo",
    "Invoice",
    "Payment",
    "PaymentTransaction",
    "AdminManagedCelerySchedule",
    "SiteMaintenance",

    "InstagramAccount",
    "InstagramMedia",
    "InstagramInsight",
    "InstagramPostQueue",

    "AdCampaign",
    "AdMetric",

    "Campaign",
    "AdGroup",
    "Creative",
    "Ad",

    "CampaignMetricHistory",
    "AdGroupMetricHistory",
    "AdMetricHistory",
    "CreativeMetricHistory",

    "CampaignOctoAnalysis",
    "CampaignOctoRecommendation",
    "HealthCenterAIAnalysis",

    "AIAnalysis",
    "ReklamAIAnaliz",
    "Report",
    "ScheduledReport",

    "CreativeTemplate",
    "CreativeProject",
    "GeneratedContent",

    "AnomalyAlert",
    "OpportunityWindow",

    "BudgetOptimizationRule",
    "BudgetOptimizationLog",

    "SystemErrorLog",
    "Notification",
    "LifecycleEmailCampaign",
    "LifecycleEmailDelivery",
    "Announcement",
    "AnnouncementDelivery",
    "LegalDocument",
    "LegalSiteSettings",
    "LegalAcceptance",
    "NotificationPreference",
    "ActivityLog",

    "SocialPost",
    "SocialPostMetricHistory",
    "Influencer",
    "InfluencerMetricHistory",

    "RawDataSnapshot",

    "ControlTowerSnapshot",
    "ControlTowerCardSnapshot",
    "ControlTowerAIAnalysis",
    "ControlTowerActionItem",
    "ControlTowerDecision",

    "AudienceHistory",
    "PlacementHistory",
    "RawPlatformData",
    "OctoScoreHistory",
    "AIRecommendationHistory",
]

if AnalyticsProperty is not None:
    __all__ += [
        "AnalyticsProperty",
        "AnalyticsDailyMetric",
        "AnalyticsLandingPageMetric",
    ]
