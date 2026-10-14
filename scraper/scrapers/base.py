from dataclasses import dataclass, field


@dataclass
class Job:
    title: str
    company: str
    location: str
    salary: str
    url: str
    source: str
    keywords: str
    description: str
    date_posted: str = field(default="")
