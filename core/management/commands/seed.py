from django.core.management.base import BaseCommand
from core.models import SampleEntity


class Command(BaseCommand):
    help = "Seeds initial database entities for development and testing"

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete existing seeded entities before inserting new ones',
        )

    def handle(self, *args, **options):
        if options['clear']:
            deleted_count, _ = SampleEntity.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Cleared {deleted_count} existing SampleEntity records."))

        sample_data = [
            {
                "title": "Initial Configuration Item",
                "description": "Baseline system configuration entity for demonstration purposes.",
                "status": "active",
                "is_active": True,
                "metadata": {"env": "development", "version": "1.0.0", "tier": "primary"},
            },
            {
                "title": "Sample Draft Entity",
                "description": "A draft item showing entity state lifecycle and JSON metadata.",
                "status": "draft",
                "is_active": False,
                "metadata": {"author": "system", "tags": ["preview", "onboarding"]},
            },
            {
                "title": "Archived Audit Sample",
                "description": "Historical record demonstrating status filtering and date indexing.",
                "status": "archived",
                "is_active": False,
                "metadata": {"retention_days": 90, "archived_reason": "sample_seed"},
            },
        ]

        created_items = []
        for item in sample_data:
            obj, created = SampleEntity.objects.get_or_create(
                title=item["title"],
                defaults={
                    "description": item["description"],
                    "status": item["status"],
                    "is_active": item["is_active"],
                    "metadata": item["metadata"],
                }
            )
            created_items.append(obj)
            status_text = "Created" if created else "Already exists"
            self.stdout.write(f" - [{status_text}] {obj.title} ({obj.id})")

        self.stdout.write(
            self.style.SUCCESS(f"Successfully finished database seeding! Total active items: {SampleEntity.objects.count()}")
        )
