#
# Part of p5: A Python package based on Processing
# Copyright (C) 2017 Abhik Pal
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#

from collections import namedtuple
from ctypes import *
import re

from pyglet.gl import *

debug = True

GLSL_VERSIONS = {'2.0': 110, '2.1': 120, '3.0': 130, '3.1': 140,
                  '3.2': 150, '3.3': 330, '4.0': 400, '4.1': 410,
                  '4.2': 420, '4.3': 430, '4.4': 440, '4.5': 450, }

def preprocess_shader(shader_source, shader_type, open_gl_version):
    """Preprocess a shader to be compatible with the given OpenGL version.

    :param shader_source: Source code of the shader.
    :type shader_source: str

    :shader_type: type of shader we are using. Should be one of
         {'vertex', 'fragment'}
    :type shader_type: str

    :param open_gl_version: The version of OpenGL we should process the
        shader for.
    :type open_gl_version: str

    :returns: The modified shader code that is compatible with the
        given OpenGL version.
    :rtype: str

    :raises TypeError: if the shader type is unsupported.

    """

    target_glsl_version = GLSL_VERSIONS[open_gl_version]

    # If the user has already defined a version string for the shader,
    # we can safely assume that they know what they are doing and we
    # don't do any preprocessing.
    #
    if "#version" in shader_source:
        return shader_source

    processed_shader = "#version {}\n".format(target_glsl_version)

    # We are assuming that the shader source code was written for
    # older versions of OpenGL (< 3.0). If the target version is
    # indeed below 3.0, we don't need to do any preprocessing.
    #
    if target_glsl_version < 130:
        return processed_shader + shader_source

    # Processing uses the following regexes to find and replace
    # identifiers (re_id) and function names (re_fn) from the old GLSL
    # versions and change them to the newever syntax.
    #
    # See: GLSL_ID_REGEX and GLSL_FN_REGEX in PGL.java (~line 1981).
    #
    re_id = "(?<![0-9A-Z_a-z])({})(?![0-9A-Z_a-z]|\\s*\\()"
    re_fn = "(?<![0-9A-Z_a-z])({})(?=\\s*\\()"

    # The search and replace strings for different shader types.
    # Terrible things will happen if the search replace isn't applied
    # in the order defined here (this is especially true for the
    # textures.)
    #
    # DO NOT CHANGE THE ORDER OF THE SEARCH/REPALCE PATTERNS.
    if shader_type == 'vertex':
        patterns = [
            (re_id, "varying", "out"),
            (re_id, "attribute", "in"),
            (re_id, "texture", "texMap"),
            (re_fn, "texture2DRect|texture2D|texture3D|textureCube", "texture")
        ]
    elif shader_type == 'fragment':
        patterns = [
            (re_id, "varying|attribute", "in"),
            (re_id, "texture", "texMap"),
            (re_fn, "texture2DRect|texture2D|texture3D|textureCube", "texture"),
            (re_id, "gl_FragColor", "_fragColor"),
        ]
        processed_shader += "out vec4 _fragColor;"
    else:
        raise TypeError("Cannot preprocess {} shader.".format(shader_type))

    for line in shader_source.split('\n'):
        new_line = line
        for regex, search, replace in patterns:
            new_line = re.sub(regex.format(search), replace, new_line)
        processed_shader += new_line + '\n'

    return processed_shader

vertex_default = """
attribute vec3 position;

uniform mat4 transform;
uniform mat4 modelview;
uniform mat4 projection;

void main()
{
    gl_Position = projection * modelview * transform * vec4(position, 1.0);
}
"""

fragment_default = """
uniform vec4 fill_color;

void main()
{
    gl_FragColor = fill_color;
}
"""

def _uvec4(uniform, data):
    glUniform4f(uniform, *data)

def _umat4(uniform, matrix):
    flattened = matrix[:]
    glUniformMatrix4fv(uniform, 1, GL_FALSE, (GLfloat * 16)(*flattened))

_uniform_function_map = {
    'vec4': _uvec4,
    'mat4': _umat4,
}

ShaderUniform = namedtuple('Uniform', ['name', 'uid', 'function'])

class Shader:
    """Represents a shader in OpenGL.

    :param source: GLSL source code of the shader.
    :type source: str

    :param kind: the type of shader {'vertex', 'fragment', etc}
    :type kind: str

    :raises TypeError: When the give shader type is not supported. 

    """
    _supported_shader_types = {
        'vertex': GL_VERTEX_SHADER,
        'fragment': GL_FRAGMENT_SHADER
    }

    def __init__(self, source, kind, version='2.0', preprocess=True):
        self.kind = kind
        self._id = None

        if preprocess:
            self.source = preprocess_shader(source, kind, version)
        else:
            self.source = source

    def compile(self):
        """Generate a shader id and compile the shader"""
        shader_type = self._supported_shader_types[self.kind]
        self._id = glCreateShader(shader_type)
        src = c_char_p(self.source.encode('utf-8'))
        glShaderSource(
            self._id,
            1,
            cast(pointer(src), POINTER(POINTER(c_char))),
            None
        )
        glCompileShader(self._id)

        if debug:
            status_code = c_int(0)
            glGetShaderiv(self._id, GL_COMPILE_STATUS, pointer(status_code))

            log_size = c_int(0)
            glGetShaderiv(self._id, GL_INFO_LOG_LENGTH, pointer(log_size))

            log_message = create_string_buffer(log_size.value)
            glGetShaderInfoLog(self._id, log_size, None, log_message)
            log_message = log_message.value.decode('utf-8')

            if len(log_message) > 0:
                print(self.source)
                print(log_message)
                # In Windows (OpenGL 3.3 + intel card) the log_message
                # is set to "No errors" on a successful compilation
                # and the code raises the Exception even though it
                # shouldn't. There should be a proper fix, but getting
                # rid of this line for now, will fix it.
                # 
                # raise Exception(log_message)

    @property
    def sid(self):
        """Return the shader id of the shader.

        :rtype: int
        :raises NameError: If the shader hasn't been created.

        """
        if self._id:
            return self._id
        else:
            raise NameError("Shader hasn't been created yet.")

    @classmethod
    def create_from_file(cls, filename, kind, **kwargs):
        """Create a shader from a file.

        :param filename: file name of the shader source code.
        :type filename: str

        :param kind: the type of shader
        :type kind: str

        :para kwargs: extra keyword arguments for the Shader
            constuctor.
        :type kwargs: dict

        :returns: A shader constucted using the given filename.
        :rtype: Shader

        """
        with open(filename) as f:
            shader_source = f.read()
        return cls(shader_source, kind, **kwargs)


class ShaderProgram:
    """A thin abstraction layer that helps work with shader programs."""

    def __init__(self):
        self._id = glCreateProgram()
        self._uniforms = {}

    @property
    def pid(self):
        """The program id of the shader."""
        return self._id

    def add_uniform(self, uniform_name, dtype):
        """Add a uniform to the shader program.

        :param uniform_name: name of the uniform.
        :type uniform_name: str

        :param dtype: data type of the uniform: 'vec3', 'mat4', etc
        :type dtype: str

        """
        uniform_function = _uniform_function_map[dtype]
        self._uniforms[uniform_name] = ShaderUniform(
            uniform_name,
            glGetUniformLocation(self.pid, uniform_name.encode()),
            uniform_function
        )

    def update_uniform(self, uniform_name, data):
        """Set data for the given uniform.

        :param uniform_name: Name of the uniform.
        :type uniform_name: str

        :param data: data to which the uniform should be set to.
        :type data: tuple

        """
        uniform = self._uniforms[uniform_name]
        uniform.function(uniform.uid, data)

    def attach(self, shader):
        """Attach a shader to the current program.

        :param shader:The shader to be attached.
        :type shader: Shader
        """
        glAttachShader(self.pid, shader.sid)

    def link(self):
        """Link the current shader."""
        glLinkProgram(self.pid)

    def activate(self):
        """Activate the current shader."""
        glUseProgram(self.pid)

    def deactivate(self):
        """Deactivate the current shader"""
        glUseProgram(0)

    def __repr__(self):
        return "{}( pid={})".format(self.__class__.__name__, self.pid)

    __str__ = __repr__
