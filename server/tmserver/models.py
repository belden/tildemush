from datetime import datetime
import re

import bcrypt
import hy
import peewee as pw
from playhouse.signals import Model, pre_save
from playhouse.postgres_ext import JSONField


from . import config

BAD_USERNAME_CHARS_RE = re.compile(r'[\:\'";%]')
MIN_PASSWORD_LEN = 12

class ScriptEngine:
    # TODO this may be merged with GameObject, ultimately. I'm not sure.
    def __init__(self):
        self.handlers = {'debug': self.debug}

    @staticmethod
    def noop(*args, **kwargs):
        pass

    def debug(self):
        return 'i am a scriptedobject'

    def add_handler(self, action, fn):
        self.handlers[action] = fn

    def handler(self, action):
        return self.handlers.get(action, self.noop)

class BaseModel(Model):
    created_at = pw.DateTimeField(default=datetime.utcnow())
    class Meta:
        database = config.get_db()

class UserAccount(BaseModel):
    """This model represents the bridge between the game world (a big tree of
    objects) and a live conncetion from a game client. A user account doesn't
    "exist," per se, in the game world, but rather is anchored to a single
    "player" object. this player object is the useraccount's window on the game
    world."""
    # TODO
    #
    # so far I've been handling the direction of mutation from a logged in user
    # *into* the gameworld. when it comes time to handle the opposite
    # direction, i need to actually be able to get data to the UserSession from
    # the gameworld. Right now an accout knows nothing about its session. A
    # refactoring is probably in order once i get the first direction going.
    #
    # ODOT

    username = pw.CharField(unique=True)
    display_name = pw.CharField(default='a gaseous cloud')
    password = pw.CharField()
    updated_at = pw.DateTimeField(null=True)
    god = pw.BooleanField(default=False)

    def _hash_password(self):
        self.password = bcrypt.hashpw(self.password.encode('utf-8'), bcrypt.gensalt())

    def check_password(self, plaintext_password):
        pw = self.password
        if type(self.password) == type(''):
            pw = self.password.encode('utf-8')
        return bcrypt.checkpw(plaintext_password.encode('utf-8'), pw)

    # TODO should this be a class method?
    # TODO should this just run in pre_save?
    def validate(self):
        if 0 != len(UserAccount.select().where(UserAccount.username == self.username)):
            raise Exception('username taken: {}'.format(self.username))

        if BAD_USERNAME_CHARS_RE.search(self.username):
            raise Exception('username has invalid character')

        if len(self.password) < MIN_PASSWORD_LEN:
            raise Exception('password too short')

    def init_player_obj(self, description=''):
        return GameObject.create(
            author=self,
            name=self.display_name,
            description=description,
            is_player_obj=True)

    @property
    def player_obj(self):
        gos = GameObject.select().where(
            GameObject.author==self,
            GameObject.is_player_obj==True)
        if gos:
            return gos[0]
        return None

    def __eq__(self, other):
        return self.username == other.username

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash((self.username,))

@pre_save(sender=UserAccount)
def pre_save_handler(cls, instance, created):
    if not created:
        instance.updated_at = datetime.utcnow()

    if created and instance.password:
        instance._hash_password()


class Script(BaseModel):
    author = pw.ForeignKeyField(UserAccount)

class ScriptRevision(BaseModel):
    code = pw.TextField()
    script = pw.ForeignKeyField(Script)

class GameObject(BaseModel):
    # every object needs to tie to a user account for authorizaton purposes
    author = pw.ForeignKeyField(UserAccount)
    name = pw.CharField()
    description = pw.TextField(default='')
    script_revision = pw.ForeignKeyField(ScriptRevision, null=True)
    is_player_obj = pw.BooleanField(default=False)
    data = JSONField(default='{}')

    @property
    def contains(self):
        return (c.inner_obj for c in Contains.select().where(Contains.outer_obj==self))

    @property
    def contained_by(self):
        model_set = list(Contains.select().where(Contains.inner_obj==self))
        if not model_set:
            return None
        if len(model_set) > 1:
            # TODO uhh
            pass
        return model_set[0].outer_obj

    @property
    def user_account(self):
        if self.is_player_obj:
            return self.author
        return None

    @property
    def engine(self):
        if not hasattr(self, '_engine'):
            # TODO should this be two steps?
            compiled = self._compile_script()
            self._engine = self._execute_script(compiled)

        return self._engine

    def _compile_script(self):
        script_text = self.script_revision.code
        with_header = '{}\n\n{}'.format(HY_HEADER, script_text)
        return hy.read_str(with_header)

    def _execute_script(self, compiled_code):
        # This evals in current scope, so ScriptEngine is available
        return hy.eval(compiled_code)

    def _ensure_data(self, data_mapping):
        # TODO check to see if data has been init'ed and init if not
        print('in _ensure_data')
        pass

    # should these be _ methods too?
    def say(self, message):
        # TODO
        print('in say')
        pass

    def set_data(self, key, value):
        # TODO
        print('in set_data')
        pass

    def get_data(self, key):
        # TODO
        print('in get_data')
        pass

    def handle_action(player_obj, action, rest):
        # TODO
        # suddenly it's time to decide how WITCH is going to work at runtime.
        #
        # Given:
        # 1. a WITCH script exists as static text in a revision object
        # 2. we need to know if a given script responds to a given action
        #
        # Then:
        # A. we need an in-RAM representation of that script: a live object instance that can dispatch actions
        # B. we need to be able to access and update the data on the GameObject model
        # C. we need to decide what the underlying class is for a live object and how to expose it via a Hy macro
        # D. we need to decide how to coordinate the GameObject model with instances of live objects
        #
        # Questions:
        # !. Should there be a static class that all live objects share? (probably)
        # @. Should a scriptrevision be lazily compiled and compiled at most once (probably)
        #
        # When a WITCH (script) macro is compiled, it should emit code that
        # instantiates an instance of ScriptEngine.
        self.engine.handler(action)(self, player_obj, rest)

    def __str__(self):
        return 'GameObject<{}> authored by {}'.format(self.name, self.author)

    def __eq__(self, other):
        script_revision = -1
        other_revision = -1
        if self.script_revision:
            script_revision = self.script_revision.id
        if other.script_revision:
            other_revision = other.script_revision.id

        return self.author.username == other.author.username\
            and self.name == other.name\
            and script_revision == other_revision

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        script_revision = -1
        if self.script_revision:
            script_revision = self.script_revision.id

        return hash((self.author.username, self.name, script_revision))

class Contains(BaseModel):
    outer_obj = pw.ForeignKeyField(GameObject)
    inner_obj = pw.ForeignKeyField(GameObject)


class Log(BaseModel):
    env = pw.CharField()
    #created_at = pw.DateTimeField(default=datetime.utcnow())
    level = pw.CharField()
    raw = pw.CharField()


MODELS = [UserAccount, Log, GameObject, Contains, Script, ScriptRevision]
