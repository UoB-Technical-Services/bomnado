from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction

from bom.models import Team, Part, PartSource, SubAssembly, SubAssemblyLineItem


class Command(BaseCommand):
    help = "Creates a demo project to help new users learn how to use Bomnado"

    def add_arguments(self, parser):
        parser.add_argument("--user", type=str, help="Username to assign as team owner (defaults to first superuser)")
        parser.add_argument("--force", action="store_true", help="Overwrite existing demo if present")

    def handle(self, *args, **options):
        with transaction.atomic():
            # Find owner user
            username = options.get("user")
            force = options.get("force", False)

            if username:
                try:
                    owner = User.objects.get(username=username)
                except User.DoesNotExist:
                    self.stderr.write(self.style.ERROR(f'User "{username}" not found'))
                    return
            else:
                # Default to first superuser
                owner = User.objects.filter(is_superuser=True).first()
                if not owner:
                    self.stderr.write(self.style.ERROR("No superuser found. Please create a superuser first."))
                    return

            # Check if demo exists
            if Team.objects.filter(name="Bicycle Team").exists() and not force:
                self.stderr.write(self.style.WARNING("Demo project already exists. Use --force to overwrite."))
                return

            # Create demo data
            self.create_demo_project(owner)

            self.stdout.write(self.style.SUCCESS(f"Successfully created demo project for {owner.username}"))

    def create_demo_project(self, owner):
        """Create a demo project with parts, assemblies and relationships"""
        # Delete existing demo if it exists
        if Team.objects.filter(name="Bicycle Team").exists():
            team = Team.objects.get(name="Bicycle Team")
            team.delete()

        # Create team
        team = Team.objects.create(name="Bicycle Team", owner=owner)
        team.users.add(owner)

        self.stdout.write("Creating bicycle demo project...")

        # Create parts
        self.stdout.write("Creating bicycle parts...")
        parts = self.create_parts(team)

        # Create bicycle project structure
        self.stdout.write("Creating bicycle assembly structure...")
        project, assemblies = self.create_bicycle_project(team)

        # Build the BOM
        self.stdout.write("Creating bill of materials...")
        self.create_bill_of_materials(project, assemblies, parts)

        self.stdout.write("Demo bicycle project created successfully!")

    def create_parts(self, team):
        """Create generic bicycle parts"""
        parts = {}

        # Frame components
        parts["frame"] = Part.objects.create(
            reference="BICYCLE-FRAME",
            name="Frame",
            spec="Bicycle frame",
            kgs=2.5,
            nature=Part.NATURE_STANDARD,
            team=team,
            qc_steps=(
                "1. Inspect for any cracks or structural defects\n"
                "2. Verify all threaded inserts are clean and undamaged\n"
                "3. Check paint finish for consistent color and coverage\n"
                "4. Measure critical dimensions against specification"
            ),
        )

        parts["handlebar"] = Part.objects.create(
            reference="HANDLEBARS",
            name="Handlebars",
            spec="Bicycle handlebars",
            kgs=0.4,
            nature=Part.NATURE_STANDARD,
            team=team,
        )

        parts["fork"] = Part.objects.create(
            reference="FORK", name="Fork", spec="Bicycle front fork", kgs=0.8, nature=Part.NATURE_STANDARD, team=team
        )

        # Wheel components
        parts["rim"] = Part.objects.create(
            reference="RIM",
            name="Wheel Rim",
            spec="Standard bicycle rim",
            kgs=0.5,
            nature=Part.NATURE_STANDARD,
            team=team,
            qc_steps=(
                "1. Check rim is true (straight) with no warping\n"
                "2. Verify spoke holes are clean and properly sized\n"
                "3. Examine rim walls for any denting or damage\n"
                "4. Confirm rim strip is properly installed for tube protection"
            ),
        )

        parts["tire"] = Part.objects.create(
            reference="TIRE", name="Tire", spec="Bicycle tire", kgs=0.4, nature=Part.NATURE_STANDARD, team=team
        )

        parts["tube"] = Part.objects.create(
            reference="INNER-TUBE",
            name="Inner Tube",
            spec="Bicycle inner tube",
            kgs=0.1,
            nature=Part.NATURE_STANDARD,
            team=team,
        )

        parts["hub"] = Part.objects.create(
            reference="HUB", name="Wheel Hub", spec="Bicycle wheel hub", kgs=0.3, nature=Part.NATURE_STANDARD, team=team
        )

        parts["spokes"] = Part.objects.create(
            reference="SPOKE",
            name="Wheel Spoke",
            spec="Bicycle wheel spoke",
            kgs=0.2,
            nature=Part.NATURE_STANDARD,
            team=team,
        )

        # Drivetrain components
        parts["chain"] = Part.objects.create(
            reference="CHAIN",
            name="Chain",
            spec="Bicycle chain",
            kgs=0.3,
            nature=Part.NATURE_STANDARD,
            team=team,
            qc_steps=(
                "1. Check chain length matches specification\n"
                "2. Verify all links move freely without binding\n"
                "3. Inspect for any stiff or damaged links\n"
                "4. Ensure master link (if present) is properly installed"
            ),
        )

        parts["front_gear"] = Part.objects.create(
            reference="GEAR-FRONT",
            name="Pedal Gears",
            spec="Front chainring set",
            kgs=0.4,
            nature=Part.NATURE_STANDARD,
            team=team,
        )

        parts["rear_gear"] = Part.objects.create(
            reference="GEAR-REAR",
            name="Wheel Gears",
            spec="Rear gear cassette",
            kgs=0.3,
            nature=Part.NATURE_STANDARD,
            team=team,
        )

        parts["pedals"] = Part.objects.create(
            reference="PEDAL",
            name="Pedal",
            spec="Standard bicycle pedal",
            kgs=0.4,
            nature=Part.NATURE_STANDARD,
            team=team,
        )

        parts["cranks"] = Part.objects.create(
            reference="CRANKS",
            name="Crank Set",
            spec="Bicycle crank arms",
            kgs=0.5,
            nature=Part.NATURE_STANDARD,
            team=team,
        )

        # Braking components
        parts["brake_lever"] = Part.objects.create(
            reference="BRAKE-LEVER",
            name="Brake Levers",
            spec="Pair of levers for the brakes",
            kgs=0.2,
            nature=Part.NATURE_STANDARD,
            team=team,
        )

        parts["brake_caliper"] = Part.objects.create(
            reference="BRAKE-CALIPER",
            name="Brake Caliper",
            spec="Pair of braking mechanism caliper",
            kgs=0.3,
            nature=Part.NATURE_STANDARD,
            team=team,
            qc_steps=(
                "1. Check for smooth pivot action\n"
                "2. Verify spring tension is within specification\n"
                "3. Ensure brake pad holders are secure\n"
                "4. Confirm caliper arms are straight and undamaged"
            ),
        )

        parts["brake_cable"] = Part.objects.create(
            reference="CABLE-BRAKE",
            name="Brake Cable",
            spec="Brake cable set",
            kgs=0.1,
            nature=Part.NATURE_STANDARD,
            team=team,
        )

        # Seat components
        parts["seat"] = Part.objects.create(
            reference="SEAT",
            name="Seat",
            spec="Bicycle seat",
            kgs=0.3,
            nature=Part.NATURE_STANDARD,
            team=team,
            qc_steps=(
                "1. Check padding firmness and even distribution\n"
                "2. Verify seat cover has no tears or defects\n"
                "3. Test mounting rails for straightness\n"
                "4. Ensure seat edges are properly finished and smooth"
            ),
        )

        parts["seat_post"] = Part.objects.create(
            reference="SEAT-POST",
            name="Seat Post",
            spec="Adjustable seat post",
            kgs=0.25,
            nature=Part.NATURE_STANDARD,
            team=team,
        )

        # Handlebar components
        parts["bell"] = Part.objects.create(
            reference="BELL",
            name="Bell",
            spec="Bicycle bell",
            kgs=0.05,
            nature=Part.NATURE_STANDARD,
            team=team,
        )

        parts["grip"] = Part.objects.create(
            reference="GRIP",
            name="Handlebar Grip",
            spec="Rubber handlebar grip",
            kgs=0.1,
            nature=Part.NATURE_STANDARD,
            team=team,
        )

        # Hardware
        parts["bolts"] = Part.objects.create(
            reference="BOLT",
            name="Bolts",
            spec="Assorted bicycle bolts",
            kgs=0.2,
            nature=Part.NATURE_STANDARD,
            team=team,
        )

        parts["nuts"] = Part.objects.create(
            reference="NUT", name="Nuts", spec="Assorted bicycle nuts", kgs=0.1, nature=Part.NATURE_STANDARD, team=team
        )

        parts["washers"] = Part.objects.create(
            reference="WASHER",
            name="Washers",
            spec="Assorted bicycle washers",
            kgs=0.05,
            nature=Part.NATURE_STANDARD,
            team=team,
        )

        # Create generic part source for each part
        for part_name, part in parts.items():
            PartSource.objects.create(
                part=part,
                partcode=f"GENERIC-{part.reference}",
                url="",
                rrp=19.99,  # Generic price
                shipping=4.99,
                minimum_order=1,
                lead_time=7,
            )

        return parts

    def create_bicycle_project(self, team):
        """Create the bicycle project with generic subassemblies"""
        # Create main project
        project = SubAssembly.objects.create(
            reference="BICYCLE",
            name="Bicycle",
            revision="1.0.0",
            is_toplevel=True,
            team=team,
            production_phase="Final Assembly",
            spec="Mountain bicycle with multiple speeds, medium frame size",
            qc_steps=(
                "1. Perform full visual inspection of all components\n"
                "2. Test all mechanical functions (steering, braking, pedalling)\n"
                "3. Verify all bolts and fasteners are properly tightened\n"
                "4. Check tire pressure meets specification\n"
                "5. Conduct test ride to ensure proper operation\n"
                "6. Verify serial numbers are recorded and match documentation"
            ),
            instructions=(
                "# Bicycle Assembly\n\n"
                "This is a generic bicycle assembly guide.\n\n"
                "## Assembly Overview\n\n"
                "1. Prepare the frame assembly\n"
                "2. Install the drivetrain\n"
                "3. Attach front and rear wheels\n"
                "4. Add braking system\n"
                "5. Install seat\n"
                "6. Final adjustments and testing"
            ),
        )

        # Create subassemblies
        frame_assembly = SubAssembly.objects.create(
            reference="FRAME-ASSEMBLY",
            name="Frame",
            revision="1.0.0",
            team=team,
            project=project,
            production_phase="SubAssembly Build",
            spec="Size medium, painted red",
            qc_steps=(
                "1. Check that the frame is painted the correct color (red)\n"
                "2. Verify all welds are high quality and free from defects\n"
                "3. Ensure the metal is rust-free and has no scratches\n"
                "4. Confirm all threading for components is clean and properly tapped\n"
                "5. Validate frame dimensions against specification sheet"
            ),
            instructions=(
                "# Frame Assembly\n\n"
                "Preparation of the main bicycle frame.\n\n"
                "## Assembly Steps\n\n"
                "1. Attach handlebar to frame\n"
                "2. Install fork\n"
                "3. Add headset components"
            ),
        )

        wheels_front = SubAssembly.objects.create(
            reference="WHEEL-FRONT",
            name="Front Wheel",
            revision="1.0.0",
            team=team,
            project=project,
            production_phase="Preparation",
            spec="Standard size with quick release",
            qc_steps=(
                "1. Verify wheel is true (no wobble) when spinning\n"
                "2. Check that quick release mechanism works smoothly\n"
                "3. Ensure proper spoke tension all around\n"
                "4. Confirm tire is evenly seated on rim\n"
                "5. Test that wheel rotates freely"
            ),
            instructions=(
                "# Front Wheel Assembly\n\n"
                "Build the front wheel.\n\n"
                "## Assembly Steps\n\n"
                "1. Lace spokes through hub\n"
                "2. Attach spokes to rim\n"
                "3. Install tire and tube\n"
                "4. Inflate to proper pressure"
            ),
        )

        wheels_rear = SubAssembly.objects.create(
            reference="WHEEL-REAR",
            name="Rear Wheel",
            revision="1.0.0",
            team=team,
            project=project,
            production_phase="Preparation",
            spec="Standard size with multiple gears",
            instructions=(
                "# Rear Wheel Assembly\n\n"
                "Build the rear wheel with gears.\n\n"
                "## Assembly Steps\n\n"
                "1. Install cassette on hub\n"
                "2. Lace spokes through hub\n"
                "3. Attach spokes to rim\n"
                "4. Install tire and tube\n"
                "5. Inflate to proper pressure"
            ),
        )

        drivetrain = SubAssembly.objects.create(
            reference="DRIVETRAIN",
            name="Drivetrain",
            revision="1.0.0",
            team=team,
            project=project,
            production_phase="SubAssembly Build",
            spec="Multi-speed setup with derailleur",
            instructions=(
                "# Drivetrain Assembly\n\n"
                "Installation of pedaling and chain system.\n\n"
                "## Assembly Steps\n\n"
                "1. Install cranks to frame\n"
                "2. Attach front gear to cranks\n"
                "3. Install pedals\n"
                "4. Connect chain"
            ),
        )

        braking = SubAssembly.objects.create(
            reference="BRAKES",
            name="Brakes",
            revision="1.0.0",
            team=team,
            project=project,
            production_phase="SubAssembly Build",
            spec="Dual caliper system with cable actuation",
            qc_steps=(
                "1. Test brake lever tension and return action\n"
                "2. Check that both calipers engage symmetrically\n"
                "3. Verify brake pads contact the rim correctly\n"
                "4. Ensure cables move freely without binding\n"
                "5. Confirm braking power is sufficient to stop bicycle quickly"
            ),
            instructions=(
                "# Braking System Assembly\n\n"
                "Installation of stopping mechanism.\n\n"
                "## Assembly Steps\n\n"
                "1. Install brake levers on handlebar\n"
                "2. Attach brake calipers to frame\n"
                "3. Connect brake cables\n"
                "4. Adjust and test"
            ),
        )

        seat_assembly = SubAssembly.objects.create(
            reference="SEAT-ASSEMBLY",
            name="Seat",
            revision="1.0.0",
            team=team,
            project=project,
            production_phase="Preparation",
            spec="Padded comfort seat with adjustable height",
            instructions=(
                "# Seat Assembly\n\n"
                "Installation of the bicycle seat.\n\n"
                "## Assembly Steps\n\n"
                "1. Insert seat post into frame\n"
                "2. Attach seat to seat post\n"
                "3. Adjust to proper height\n"
                "4. Secure all bolts"
            ),
        )

        # Create additional subassemblies to demonstrate nesting
        handlebar_assembly = SubAssembly.objects.create(
            reference="HANDLEBAR-ASSEMBLY",
            name="Handlebar Assembly",
            revision="1.0.0",
            team=team,
            project=project,
            production_phase="Preparation",
            spec="Standard curved handlebar with rubber grips",
            qc_steps=(
                "1. Check that handlebar is straight and properly aligned\n"
                "2. Verify brake levers are positioned correctly and tightened\n"
                "3. Ensure grips are securely attached and don't rotate\n"
                "4. Test bell for proper sound and operation\n"
                "5. Confirm all bolts are tightened to specification"
            ),
            instructions=(
                "# Handlebar Assembly\n\n"
                "Assembly of handlebar with components.\n\n"
                "## Assembly Steps\n\n"
                "1. Attach grips to handlebar ends\n"
                "2. Mount brake levers in position\n"
                "3. Install bell on handlebar\n"
                "4. Secure all components"
            ),
        )

        pedal_assembly = SubAssembly.objects.create(
            reference="PEDAL-ASSEMBLY",
            name="Pedal Assembly",
            revision="1.0.0",
            team=team,
            project=project,
            production_phase="Preparation",
            spec="Platform pedals with reflectors",
            instructions=(
                "# Pedal Assembly\n\n"
                "Assembly and preparation of pedals.\n\n"
                "## Assembly Steps\n\n"
                "1. Apply thread compound to pedal threads\n"
                "2. Identify left and right pedals\n"
                "3. Thread pedals into cranks (note: reverse thread on left pedal)"
            ),
        )

        # Create front brake assembly
        front_brake = SubAssembly.objects.create(
            reference="BRAKE-FRONT",
            name="Front Brake",
            revision="1.0.0",
            team=team,
            project=project,
            production_phase="Preparation",
            spec="Front caliper brake system",
            qc_steps=(
                "1. Check that brake pads are properly aligned with rim\n"
                "2. Verify brake arm spring tension is balanced\n"
                "3. Ensure brake cable moves freely through housing\n"
                "4. Test brake pad clearance from rim when not engaged"
            ),
            instructions=(
                "# Front Brake Assembly\n\n"
                "Assembly of front brake components.\n\n"
                "## Assembly Steps\n\n"
                "1. Attach front brake caliper to fork\n"
                "2. Route brake cable through frame guides\n"
                "3. Connect cable to brake lever\n"
                "4. Adjust cable tension for proper stopping power"
            ),
        )

        # Create rear brake assembly
        rear_brake = SubAssembly.objects.create(
            reference="BRAKE-REAR",
            name="Rear Brake",
            revision="1.0.0",
            team=team,
            project=project,
            production_phase="Preparation",
            spec="Rear caliper brake system",
            qc_steps=(
                "1. Check that brake pads are properly aligned with rim\n"
                "2. Verify brake arm spring tension is balanced\n"
                "3. Ensure brake cable moves freely through housing\n"
                "4. Test brake pad clearance from rim when not engaged"
            ),
            instructions=(
                "# Rear Brake Assembly\n\n"
                "Assembly of rear brake components.\n\n"
                "## Assembly Steps\n\n"
                "1. Attach rear brake caliper to frame\n"
                "2. Route brake cable through frame guides\n"
                "3. Connect cable to brake lever\n"
                "4. Adjust cable tension for proper stopping power"
            ),
        )

        return project, {
            "frame": frame_assembly,
            "wheel_front": wheels_front,
            "wheel_rear": wheels_rear,
            "drivetrain": drivetrain,
            "braking": braking,
            "seat": seat_assembly,
            "handlebar": handlebar_assembly,
            "pedal": pedal_assembly,
            "front_brake": front_brake,
            "rear_brake": rear_brake,
        }

    def create_bill_of_materials(self, project, assemblies, parts):
        """Create the bill of materials linking parts to assemblies"""
        # Frame assembly components
        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["frame"], child_part=parts["frame"], quantity=1, notes="Main frame"
        )

        # Connect handlebar subassembly to frame
        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["frame"],
            child_subassembly=assemblies["handlebar"],
            quantity=1,
            notes="Steering system",
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["frame"],
            child_part=parts["fork"],
            quantity=1,
            notes="Front fork for wheel attachment",
        )

        # Connect pedal subassembly to frame
        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["frame"], child_subassembly=assemblies["pedal"], quantity=1, notes="Pedal system"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["frame"], child_part=parts["bolts"], quantity=6, notes="For frame assembly"
        )

        # Front wheel assembly
        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["wheel_front"], child_part=parts["rim"], quantity=1, notes="Front wheel rim"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["wheel_front"], child_part=parts["hub"], quantity=1, notes="Front wheel hub"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["wheel_front"], child_part=parts["spokes"], quantity=16, notes="Front wheel spokes"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["wheel_front"], child_part=parts["tire"], quantity=1, notes="Front tire"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["wheel_front"], child_part=parts["tube"], quantity=1, notes="Front inner tube"
        )

        # Rear wheel assembly
        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["wheel_rear"], child_part=parts["rim"], quantity=1, notes="Rear wheel rim"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["wheel_rear"], child_part=parts["hub"], quantity=1, notes="Rear wheel hub"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["wheel_rear"], child_part=parts["spokes"], quantity=16, notes="Rear wheel spokes"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["wheel_rear"], child_part=parts["tire"], quantity=1, notes="Rear tire"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["wheel_rear"], child_part=parts["tube"], quantity=1, notes="Rear inner tube"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["wheel_rear"], child_part=parts["rear_gear"], quantity=1, notes="Rear gear cassette"
        )

        # Handlebar subassembly components
        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["handlebar"], child_part=parts["handlebar"], quantity=1, notes="Main handlebar"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["handlebar"], child_part=parts["brake_lever"], quantity=1, notes="Brake levers"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["handlebar"], child_part=parts["bell"], quantity=1, notes="Warning bell"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["handlebar"], child_part=parts["grip"], quantity=2, notes="Left and right grips"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["handlebar"], child_part=parts["bolts"], quantity=3, notes="For securing components"
        )

        # Pedal subassembly components
        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["pedal"], child_part=parts["pedals"], quantity=2, notes="Left and right pedals"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["pedal"], child_part=parts["bolts"], quantity=2, notes="For pedal assembly"
        )

        # Drivetrain assembly
        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["drivetrain"], child_part=parts["cranks"], quantity=1, notes="Crank arms"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["drivetrain"], child_part=parts["front_gear"], quantity=1, notes="Front chainring"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["drivetrain"], child_part=parts["chain"], quantity=1, notes="Drive chain"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["drivetrain"], child_part=parts["bolts"], quantity=4, notes="For drivetrain assembly"
        )

        # Braking system - now using front and rear brake subassemblies
        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["braking"],
            child_subassembly=assemblies["front_brake"],
            quantity=1,
            notes="Front brake assembly",
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["braking"],
            child_subassembly=assemblies["rear_brake"],
            quantity=1,
            notes="Rear brake assembly",
        )

        # Add parts to the brake lever portion that stays with the main braking system
        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["braking"], child_part=parts["brake_lever"], quantity=1, notes="Pair of brake levers"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["braking"], child_part=parts["bolts"], quantity=2, notes="For brake lever mounting"
        )

        # Front brake components
        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["front_brake"],
            child_part=parts["brake_caliper"],
            quantity=1,
            notes="Front brake caliper",
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["front_brake"],
            child_part=parts["brake_cable"],
            quantity=1,
            notes="Front brake cable",
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["front_brake"],
            child_part=parts["bolts"],
            quantity=2,
            notes="For front brake mounting",
        )

        # Rear brake components
        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["rear_brake"],
            child_part=parts["brake_caliper"],
            quantity=1,
            notes="Rear brake caliper",
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["rear_brake"], child_part=parts["brake_cable"], quantity=1, notes="Rear brake cable"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["rear_brake"], child_part=parts["bolts"], quantity=2, notes="For rear brake mounting"
        )

        # Seat assembly
        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["seat"], child_part=parts["seat"], quantity=1, notes="Main seat"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["seat"], child_part=parts["seat_post"], quantity=1, notes="Adjustable seat post"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=assemblies["seat"], child_part=parts["bolts"], quantity=2, notes="For seat attachment"
        )

        # Add all subassemblies to main project
        SubAssemblyLineItem.objects.create(
            subassembly=project,
            child_subassembly=assemblies["frame"],
            quantity=1,
            notes="The main structure of the bicycle",
        )

        SubAssemblyLineItem.objects.create(
            subassembly=project, child_subassembly=assemblies["wheel_front"], quantity=1, notes="Front wheel assembly"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=project,
            child_subassembly=assemblies["wheel_rear"],
            quantity=1,
            notes="Rear wheel with gears assembly",
        )

        SubAssemblyLineItem.objects.create(
            subassembly=project, child_subassembly=assemblies["drivetrain"], quantity=1, notes="The pedaling system"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=project, child_subassembly=assemblies["braking"], quantity=1, notes="The braking system"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=project, child_subassembly=assemblies["seat"], quantity=1, notes="The seat and post"
        )

        # Add some hardware directly to main project
        SubAssemblyLineItem.objects.create(
            subassembly=project, child_part=parts["nuts"], quantity=10, notes="Assorted nuts for final assembly"
        )

        SubAssemblyLineItem.objects.create(
            subassembly=project, child_part=parts["washers"], quantity=15, notes="Assorted washers for final assembly"
        )
