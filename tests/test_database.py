import pytest
from app.database.session import SessionLocal, engine, Base
from app.database.models import Movie, Script, Episode, Video, Job, Setting

@pytest.fixture(scope="module")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    yield db
    db.close()

def test_create_movie_and_script(db_session):
    movie = Movie(
        title="Inception Test",
        original_title="Inception",
        release_year=2010,
        genre="Khoa học viễn tưởng",
        potential_score=95.5
    )
    db_session.add(movie)
    db_session.commit()
    assert movie.id is not None

    script = Script(
        movie_id=movie.id,
        title=f"Kịch bản {movie.title}",
        target_episodes=3,
        style="dramatic"
    )
    db_session.add(script)
    db_session.commit()
    assert script.id is not None

    episode = Episode(
        script_id=script.id,
        episode_number=1,
        hook_text="Bạn có tin giấc mơ này là thật?",
        content_text="Nội dung tóm tắt đoạn đầu phim...",
        status="draft"
    )
    db_session.add(episode)
    db_session.commit()
    assert episode.id is not None
    assert episode.script.movie.title == "Inception Test"

def test_create_and_update_job(db_session):
    job = Job(
        job_type="TestJob",
        status="pending",
        progress=0
    )
    db_session.add(job)
    db_session.commit()
    assert job.id is not None

    job.status = "completed"
    job.progress = 100
    db_session.commit()
    
    updated_job = db_session.query(Job).filter(Job.id == job.id).first()
    assert updated_job.status == "completed"
    assert updated_job.progress == 100
