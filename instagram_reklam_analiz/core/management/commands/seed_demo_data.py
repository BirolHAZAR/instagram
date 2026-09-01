def handle(self, *args, **options):
    random.seed(20260703)
    now = timezone.now()
    today = now.date()

    call_command("seed_platforms", verbosity=0)
    self._ensure_marketplaces()

    with transaction.atomic():
        User = get_user_model()

        Influencer.objects.filter(
            normalized_handle__startswith="demo_influencer_"
        ).delete()

        # ==========================================================
        # DEMO USER
        # ==========================================================
        # Demo kullanıcısı KESİNLİKLE silinmez.
        # Varsa mevcut kullanıcı kullanılır.
        # Yoksa ilk kez oluşturulur.
        # ==========================================================

        user, created = User.objects.get_or_create(
            username="demo",
            defaults={
                "email": "demo@reklamanaliz.net",
                "first_name": "Demo",
                "last_name": "Kullanici",
                "is_active": True,
                "is_staff": False,
                "is_superuser": False,
            },
        )

        if created:
            user.set_password("Demo12345!")
            user.save(update_fields=["password"])

        else:
            # Mevcut demo hesabına dokunuyoruz.
            # Kullanıcının mevcut verileri korunur.
            update_fields = []

            if not user.is_active:
                user.is_active = True
                update_fields.append("is_active")

            if not user.email:
                user.email = "demo@reklamanaliz.net"
                update_fields.append("email")

            if not user.first_name:
                user.first_name = "Demo"
                update_fields.append("first_name")

            if not user.last_name:
                user.last_name = "Kullanici"
                update_fields.append("last_name")

            if update_fields:
                user.save(update_fields=update_fields)

        # ==========================================================
        # EMAIL
        # ==========================================================

        EmailAddress.objects.update_or_create(
            user=user,
            email=user.email,
            defaults={
                "verified": True,
                "primary": True,
            },
        )

        # ==========================================================
        # PLAN
        # ==========================================================

        plan = self._agency_plan()

        # ==========================================================
        # ORGANIZATION
        # ==========================================================

        organization = (
            Organization.objects.filter(
                owner=user,
                name="Demo Ajans",
            )
            .order_by("id")
            .first()
        )

        if organization is None:
            organization = Organization.objects.create(
                name="Demo Ajans",
                owner=user,
                active_plan=plan,
                report_brand_name="Demo Ajans Performans Merkezi",
                report_footer_note=(
                    "Satış sunumu için oluşturulmuş demo veridir."
                ),
                is_active=True,
            )
        else:
            organization.active_plan = plan
            organization.report_brand_name = (
                "Demo Ajans Performans Merkezi"
            )
            organization.report_footer_note = (
                "Satış sunumu için oluşturulmuş demo veridir."
            )
            organization.is_active = True

            organization.save(
                update_fields=[
                    "active_plan",
                    "report_brand_name",
                    "report_footer_note",
                    "is_active",
                ]
            )

        # ==========================================================
        # ORGANIZATION MEMBER
        # ==========================================================

        OrganizationMember.objects.update_or_create(
            organization=organization,
            user=user,
            defaults={
                "role": OrganizationMember.ROLE_OWNER,
                "can_manage_clients": True,
                "can_manage_accounts": True,
                "can_manage_competitors": True,
                "can_view_reports": True,
                "can_manage_members": True,
                "can_manage_billing": True,
                "menu_permissions": (
                    all_agency_menu_permission_keys()
                ),
                "is_active": True,
                "invited_email": user.email,
            },
        )

        # ==========================================================
        # CLIENT
        # ==========================================================

        client = (
            AgencyClient.objects.filter(
                organization=organization,
                name="Demo Marka",
            )
            .order_by("id")
            .first()
        )

        if client is None:
            client = AgencyClient.objects.create(
                organization=organization,
                name="Demo Marka",
                legal_name="Demo Marka Ticaret A.S.",
                website="https://demo.reklamanaliz.net",
                contact_name="Demo Marka Ekibi",
                contact_email="marka@demo.reklamanaliz.net",
                notes="Sunum verileri bu marka altında toplanır.",
                is_active=True,
            )
        else:
            client.legal_name = "Demo Marka Ticaret A.S."
            client.website = "https://demo.reklamanaliz.net"
            client.contact_name = "Demo Marka Ekibi"
            client.contact_email = (
                "marka@demo.reklamanaliz.net"
            )
            client.notes = (
                "Sunum verileri bu marka altında toplanır."
            )
            client.is_active = True

            client.save(
                update_fields=[
                    "legal_name",
                    "website",
                    "contact_name",
                    "contact_email",
                    "notes",
                    "is_active",
                ]
            )

        # ==========================================================
        # SUBSCRIPTION
        # ==========================================================

        subscription = (
            UserSubscription.objects.filter(
                user=user,
                organization=organization,
            )
            .order_by("-id")
            .first()
        )

        if subscription is None:
            subscription = UserSubscription.objects.create(
                user=user,
                organization=organization,
                plan=plan,
                start_date=today - timedelta(days=15),
                end_date=today + timedelta(days=365),
                is_active=True,
                billing_period=UserSubscription.BILLING_MONTHLY,
                next_renewal_date=today + timedelta(days=30),
            )
        else:
            subscription.plan = plan
            subscription.is_active = True

            subscription.save(
                update_fields=[
                    "plan",
                    "is_active",
                ]
            )

        # ==========================================================
        # AI CREDIT BALANCE
        # ==========================================================

        UserAICreditBalance.objects.update_or_create(
            user=user,
            organization=organization,
            subscription=subscription,
            defaults={
                "cycle_start": today.replace(day=1),
                "cycle_end": today + timedelta(days=30),
                "plan_credits": 100000,
                "purchased_credits": 50000,
                "used_credits": 12250,
                "current_balance": 137750,
            },
        )

        # ==========================================================
        # PRODUCT RESEARCH BALANCE
        # ==========================================================

        UserProductResearchBalance.objects.update_or_create(
            user=user,
            organization=organization,
            defaults={
                "cycle_start": today.replace(day=1),
                "cycle_end": today + timedelta(days=30),
                "purchased_units": 2500,
                "used_units": 320,
                "current_balance": 2180,
            },
        )

        # ==========================================================
        # PLATFORM DEMO
        # ==========================================================

        ad_summary = self._create_platform_demo(
            user,
            organization,
            client,
            now,
            today,
        )

        # ==========================================================
        # MARKETPLACE DEMO
        # ==========================================================

        marketplace_summary = self._create_marketplace_demo(
            user,
            organization,
            client,
            subscription,
            now,
            today,
        )

        # ==========================================================
        # SUPPLEMENTAL DEMO
        # ==========================================================

        supplemental_summary = self._create_supplemental_demo(
            user,
            client,
            ad_summary,
            now,
            today,
        )

        # ==========================================================
        # ANOMALIES
        # ==========================================================

        anomaly_count = self._create_anomalies(
            user,
            ad_summary["ads"],
            now,
        )

        # ==========================================================
        # OPPORTUNITIES
        # ==========================================================

        opportunity_count = self._create_opportunities(
            user,
            now,
        )

        # ==========================================================
        # FINAL PRESENTATION
        # ==========================================================

        final_summary = self._finalize_demo_presentation(
            user,
            subscription,
        )

    self.stdout.write(
        self.style.SUCCESS(
            "Demo veri olusturuldu."
        )
    )

    self.stdout.write(
        "Kullanici: demo"
    )

    self.stdout.write(
        "Sifre: Demo12345!"
    )

    self.stdout.write(
        f"Platform hesabi: "
        f"{ad_summary['accounts']}"
    )

    self.stdout.write(
        f"Kampanya: "
        f"{ad_summary['campaigns']}"
    )

    self.stdout.write(
        f"Reklam grubu: "
        f"{ad_summary['ad_groups']}"
    )

    self.stdout.write(
        f"Reklam: "
        f"{len(ad_summary['ads'])}"
    )

    self.stdout.write(
        f"GA4 property/metrik gunu: "
        f"{ad_summary['ga_properties']}/"
        f"{ad_summary['ga_days']}"
    )

    self.stdout.write(
        f"Anomali/Firsat: "
        f"{anomaly_count}/"
        f"{opportunity_count}"
    )

    self.stdout.write(
        f"Pazaryeri hesabi: "
        f"{marketplace_summary['accounts']}"
    )

    self.stdout.write(
        f"Pazaryeri urunu: "
        f"{marketplace_summary['products']}"
    )

    self.stdout.write(
        f"Pazaryeri metrik gecmisi: "
        f"{marketplace_summary['history']}"
    )

    self.stdout.write(
        "Ek moduller: "
        f"rakip={supplemental_summary['competitors']}, "
        f"organik={supplemental_summary['social_posts']}, "
        f"influencer={supplemental_summary['influencers']}, "
        f"octo={supplemental_summary['octo_tasks']}, "
        f"control_tower="
        f"{supplemental_summary['control_tower_items']}, "
        f"bildirim="
        f"{final_summary['notifications']}, "
        f"raw="
        f"{supplemental_summary['raw_snapshots']}"
    )