
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from .database import Base, engine, get_db
from . import models  # Ensure models are registered with Base
from .models import Task, User
from .schemas import (
    TaskCreate,
    TaskResponse,
    UserCreate,
    UserResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Learning-project alternative to Alembic migrations.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Task Management API",
    lifespan=lifespan,
)

DBSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@app.get("/")
def root():
    return {"message": "Task API is running"}


# --------------------
# Authentication
# --------------------

@app.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_user(user_data: UserCreate, db: DBSession):
    existing_user = db.scalar(
        select(User).where(
            (User.username == user_data.username)
            | (User.email == user_data.email)
        )
    )

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already registered",
        )

    user = User(
        username=user_data.username,
        email=user_data.email,
        password_hash=hash_password(user_data.password),
    )

    db.add(user)

    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already registered",
        ) from None

    return user


@app.post("/auth/login")
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DBSession,
):
    # OAuth2PasswordRequestForm uses the field named "username".
    # In this demo, enter your username here, not your email.
    user = db.scalar(
        select(User).where(User.username == form_data.username)
    )

    if (
        user is None
        or not verify_password(
            form_data.password,
            user.password_hash,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user.id)

    return {
        "access_token": token,
        "token_type": "bearer",
    }


@app.get("/users/me", response_model=UserResponse)
def read_current_user(current_user: CurrentUser):
    return current_user


# --------------------
# Tasks
# --------------------

@app.post(
    "/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    task_data: TaskCreate,
    db: DBSession,
    current_user: CurrentUser,
):
    task = Task(
        **task_data.model_dump(),
        user_id=current_user.id,
    )

    db.add(task)
    db.commit()
    db.refresh(task)

    return task


@app.get("/tasks", response_model=list[TaskResponse])
def get_tasks(
    db: DBSession,
    current_user: CurrentUser,
    completed: bool | None = None,
):
    query = select(Task).where(Task.user_id == current_user.id)

    if completed is not None:
        query = query.where(Task.completed == completed)

    return list(db.scalars(query).all())


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: int,
    db: DBSession,
    current_user: CurrentUser,
):
    task = db.scalar(
        select(Task).where(
            Task.id == task_id,
            Task.user_id == current_user.id,
        )
    )

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    return task


@app.put("/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: int,
    task_data: TaskCreate,
    db: DBSession,
    current_user: CurrentUser,
):
    task = db.scalar(
        select(Task).where(
            Task.id == task_id,
            Task.user_id == current_user.id,
        )
    )

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    task.title = task_data.title
    task.description = task_data.description
    task.completed = task_data.completed

    db.commit()
    db.refresh(task)

    return task


@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: int,
    db: DBSession,
    current_user: CurrentUser,
):
    task = db.scalar(
        select(Task).where(
            Task.id == task_id,
            Task.user_id == current_user.id,
        )
    )

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    db.delete(task)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
