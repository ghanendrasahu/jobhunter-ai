"""Generate a sample PDF resume for testing the JobHunter AI pipeline."""

from fpdf import FPDF


class SampleResume(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 10, "Jane Doe", new_x="LMARGIN", new_y="NEXT", align="C")
        self.set_font("Helvetica", "", 10)
        self.cell(0, 6, "jane.doe@email.com | (555) 123-4567 | linkedin.com/in/janedoe", align="C")
        self.ln(8)

    def section(self, title):
        self.set_font("Helvetica", "B", 12)
        self.set_fill_color(240, 240, 240)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT", fill=True)
        self.ln(2)

    def body_text(self, txt):
        self.set_font("Helvetica", "", 10)
        self.multi_cell(0, 5, txt)
        self.ln(2)


def generate_sample_resume(output_path: str = "sample_resume.pdf"):
    pdf = SampleResume()
    pdf.add_page()

    pdf.section("Professional Summary")
    pdf.body_text(
        "Experienced Software Engineer with 5+ years building scalable web applications. "
        "Proficient in Python, JavaScript, React, and AWS. Passionate about AI/ML and "
        "building products that delight users."
    )

    pdf.section("Skills")
    pdf.body_text(
        "Languages: Python, JavaScript, TypeScript, SQL\n"
        "Frameworks: React, Node.js, FastAPI, Django\n"
        "Cloud & DevOps: AWS (EC2, S3, Lambda), Docker, CI/CD\n"
        "AI/ML: LangChain, OpenAI API, TensorFlow\n"
        "Tools: Git, Linux, PostgreSQL, Redis"
    )

    pdf.section("Experience")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, "Senior Software Engineer | TechCorp Inc.", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 5, "Jan 2022 - Present | San Francisco, CA", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.body_text(
        "- Led a team of 4 engineers to build a real-time analytics dashboard serving 50K+ users\n"
        "- Migrated monolith to microservices on AWS, reducing deployment time by 70%\n"
        "- Implemented CI/CD pipelines using GitHub Actions and Terraform\n"
        "- Designed RESTful APIs with FastAPI and PostgreSQL"
    )

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, "Software Engineer | StartupXYZ", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 5, "Jun 2019 - Dec 2021 | New York, NY", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.body_text(
        "- Built a React-based SaaS platform with 10K+ monthly active users\n"
        "- Developed Python ETL pipelines processing 1M+ records daily\n"
        "- Integrated third-party APIs (Stripe, SendGrid, AWS S3)"
    )

    pdf.section("Education")
    pdf.body_text(
        "B.S. in Computer Science\n"
        "University of California, Berkeley | 2015 - 2019\n"
        "GPA: 3.8/4.0 | Dean's List"
    )

    pdf.section("Projects")
    pdf.body_text(
        "AI Chatbot Assistant | Built a LangChain-powered chatbot using GPT-4 and RAG\n"
        "E-Commerce Platform | Full-stack React/Node.js app with payment processing\n"
        "Open Source Contributor | Active contributor to FastAPI and LangChain repos"
    )

    pdf.output(output_path)
    print(f"Sample resume created: {output_path}")


if __name__ == "__main__":
    generate_sample_resume()