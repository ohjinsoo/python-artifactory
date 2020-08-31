"""
Definition of all artifactory objects.
"""
import json
import logging
from typing import List, Optional, Dict, Tuple, Union

from pathlib import Path
import requests
from requests import Response
from pydantic import parse_obj_as, SecretStr

from pyartifactory.exception import (
    UserNotFoundException,
    UserAlreadyExistsException,
    GroupNotFoundException,
    RepositoryAlreadyExistsException,
    GroupAlreadyExistsException,
    RepositoryNotFoundException,
    ArtifactoryException,
    PermissionAlreadyExistsException,
    PermissionNotFoundException,
    InvalidTokenDataException,
    AqlException,
    PropertyNotFoundException,
    ArtifactNotFoundException,
)

from pyartifactory.models import (
    AuthModel,
    ApiKeyModel,
    PasswordModel,
    AccessTokenModel,
    Group,
    LocalRepositoryResponse,
    VirtualRepositoryResponse,
    RemoteRepositoryResponse,
    AnyRepository,
    AnyRepositoryResponse,
    UserResponse,
    NewUser,
    SimpleUser,
    User,
    Permission,
    SimplePermission,
    ArtifactPropertiesResponse,
    ArtifactStatsResponse,
    Aql,
    ArtifactInfoResponse,
)
from pyartifactory.models.artifact import (
    ArtifactFileInfoResponse,
    ArtifactFolderInfoResponse,
)

logger = logging.getLogger("pyartifactory")


class Artifactory:
    """Models artifactory."""

    def __init__(
        self,
        url: str,
        auth: Tuple[str, SecretStr],
        verify: bool = True,
        cert: str = None,
    ):
        self.artifactory = AuthModel(url=url, auth=auth, verify=verify, cert=cert)
        self.users = ArtifactoryUser(self.artifactory)
        self.groups = ArtifactoryGroup(self.artifactory)
        self.security = ArtifactorySecurity(self.artifactory)
        self.repositories = ArtifactoryRepository(self.artifactory)
        self.artifacts = ArtifactoryArtifact(self.artifactory)
        self.aql = ArtifactoryAql(self.artifactory)
        self.permissions = ArtifactoryPermission(self.artifactory)


class ArtifactoryObject:
    """Models the artifactory object."""

    def __init__(self, artifactory: AuthModel) -> None:
        self._artifactory = artifactory
        self._auth = (
            self._artifactory.auth[0],
            self._artifactory.auth[1].get_secret_value(),
        )
        self._verify = self._artifactory.verify
        self._cert = self._artifactory.cert
        self.session = requests.Session()

    def _get(self, route: str, **kwargs) -> Response:
        """
        :param route: API Route
        :param kwargs: Additional parameters to add the request
        :returns  An HTTP response
        """
        return self._generic_http_method_request("get", route, **kwargs)

    def _post(self, route: str, **kwargs) -> Response:
        """
        :param route: API Route
        :param kwargs: Additional parameters to add the request
        :returns  An HTTP response
        """
        return self._generic_http_method_request("post", route, **kwargs)

    def _put(self, route: str, **kwargs) -> Response:
        """
        :param route: API Route
        :param kwargs: Additional parameters to add the request
        :returns  An HTTP response
        """
        return self._generic_http_method_request("put", route, **kwargs)

    def _delete(self, route: str, **kwargs) -> Response:
        """
        :param route: API Route
        :param kwargs: Additional parameters to add the request
        :returns  An HTTP response
        """
        return self._generic_http_method_request("delete", route, **kwargs)

    def _generic_http_method_request(
        self, method: str, route: str, raise_for_status: bool = True, **kwargs
    ) -> Response:
        """
        :param method: HTTP method to use
        :param route: API Route
        :param kwargs: Additional parameters to add the request
        :return: An HTTP response
        """

        http_method = getattr(self.session, method)
        response: Response = http_method(
            f"{self._artifactory.url}/{route}",
            auth=self._auth,
            **kwargs,
            verify=self._verify,
            cert=self._cert,
        )
        if raise_for_status:
            response.raise_for_status()
        return response


class ArtifactoryUser(ArtifactoryObject):
    """Models an artifactory user."""

    _uri = "security/users"

    def create(self, user: NewUser) -> UserResponse:
        """
        Create user
        :param user: NewUser object
        :return: User
        """
        username = user.name
        try:
            self.get(username)
            logger.error("User %s already exists", username)
            raise UserAlreadyExistsException(f"User {username} already exists")
        except UserNotFoundException:
            data = user.dict()
            data["password"] = user.password.get_secret_value()
            self._put(f"api/{self._uri}/{username}", json=data)
            logging.info("User %s successfully created", username)
            logger.debug("User %s successfully created", username)
            return self.get(user.name)

    def get(self, name: str) -> UserResponse:
        """
        Read user from artifactory. Fill object if exist
        :param name: Name of the user to retrieve
        :return: UserModel
        """
        try:
            response = self._get(f"api/{self._uri}/{name}")
            logger.debug("User %s found", name)
            return UserResponse(**response.json())
        except requests.exceptions.HTTPError as error:
            if error.response.status_code == 404 or error.response.status_code == 400:
                logger.error("User %s does not exist", name)
                raise UserNotFoundException(f"{name} does not exist")
            raise ArtifactoryException from error

    def list(self) -> List[SimpleUser]:
        """
        Lists all the users
        :return: UserList
        """
        response = self._get(f"api/{self._uri}")
        logger.debug("List all users successful")
        return [SimpleUser(**user) for user in response.json()]

    def update(self, user: User) -> UserResponse:
        """
        Updates an artifactory user
        :param user: NewUser object
        :return: UserModel
        """
        username = user.name
        self.get(username)
        self._post(f"api/{self._uri}/{username}", json=user.dict())
        logging.info("User %s successfully updated", username)
        self._post(
            f"api/{self._uri}/{username}",
            json=user.dict(exclude={"lastLoggedIn", "realm"}),
        )
        logger.debug("User %s successfully updated", username)
        return self.get(username)

    def delete(self, name: str) -> None:
        """
        Remove user
        :param name: Name of the user to delete
        :return: None
        """
        self.get(name)
        self._delete(f"api/{self._uri}/{name}")
        logger.debug("User %s successfully deleted", name)

    def unlock(self, name: str) -> None:
        """
        Unlock user
        Even if the user doesn't exist, it succeed too
        :param name: Name of the user to unlock
        :return none
        """
        self._post(f"api/security/unlockUsers/{name}")
        logger.debug("User % successfully unlocked", name)


class ArtifactorySecurity(ArtifactoryObject):
    """Models artifactory security."""

    _uri = "security"

    def get_encrypted_password(self) -> PasswordModel:
        """
        Get the encrypted password of the authenticated requestor.
        :return: str
        """
        response = self._get(f"api/{self._uri}/encryptedPassword")
        logger.debug("Encrypted password successfully delivered")
        return PasswordModel(**response.json())

    def create_access_token(
        self,
        user_name: str,
        expires_in: int = 3600,
        refreshable: bool = False,
        groups: Optional[List[str]] = None,
    ) -> AccessTokenModel:
        """
        Creates an access token.

        :param user_name: Name of the user to whom an access key should be granted. transient token
                          is created if user doesn't exist in artifactory.
        :param expires_in: Expiry time for the token in seconds. For eternal tokens specify 0.
        :param refreshable: If set to true token can be refreshed using the refresh token returned.
        :param groups: A list of groups the token has membership of.
                       If an existing user in artifactory is used with existing memberships
                       groups are automatically implied without specification.
        :return: AccessToken
        """
        payload = {
            "username": user_name,
            "expires_in": expires_in,
            "refreshable": refreshable,
        }
        if groups:
            if not isinstance(groups, list):
                raise ValueError(groups)
            scope = f'member-of-groups:"{", ".join(groups)}"'
            payload.update({"scope": scope})
        response = self._post(
            f"api/{self._uri}/token", data=payload, raise_for_status=False
        )
        if response.ok:
            return AccessTokenModel(**response.json())
        raise InvalidTokenDataException(
            response.json().get("error_description", "Unknown error")
        )

    def revoke_access_token(self, token: str = None, token_id: str = None) -> bool:
        """
        Revokes an access token.

        :param token: The token to revoke
        :param token_id: The id of a token to revoke
        :return: bool True or False indicating success or failure of token revocation attempt.
        """
        if not any([token, token_id]):
            logger.error("Neither a token or a token id was specified")
            raise InvalidTokenDataException
        payload: Dict[str, Optional[str]] = {"token": token} if token else {
            "token_id": token_id
        }
        response = self._post(
            f"api/{self._uri}/token/revoke", data=payload, raise_for_status=False
        )
        if response.ok:
            logger.debug("Token revoked successfully, or token did not exist")
            return True
        logger.error("Token revocation unsuccessful, response was %s", response.text)
        return False

    def create_api_key(self) -> ApiKeyModel:
        """
        Create an API key for the current user.
        :return: Error if API key already exists - use regenerate API key instead.
        """
        response = self._post(f"api/{self._uri}/apiKey")
        logger.debug("API Key successfully created")
        return ApiKeyModel(**response.json())

    def regenerate_api_key(self) -> ApiKeyModel:
        """
        Regenerate an API key for the current user
        :return: API key
        """
        response = self._put(f"api/{self._uri}/apiKey")
        logger.debug("API Key successfully regenerated")
        return ApiKeyModel(**response.json())

    def get_api_key(self) -> ApiKeyModel:
        """
        Get the current user's own API key
        :return: API key
        """
        response = self._get(f"api/{self._uri}/apiKey")
        logger.debug("API Key successfully delivered")
        return ApiKeyModel(**response.json())

    def revoke_api_key(self) -> None:
        """
        Revokes the current user's API key
        :return: None
        """
        self._delete(f"api/{self._uri}/apiKey")
        logger.debug("API Key successfully revoked")

    def revoke_user_api_key(self, name: str) -> None:
        """
        Revokes the API key of another user
        :param name: name of the user to whom api key has to be revoked
        :return: None
        """
        self._delete(f"api/{self._uri}/apiKey/{name}")
        logger.debug("User API Key successfully revoked")


class ArtifactoryGroup(ArtifactoryObject):
    """Models artifactory groups."""

    _uri = "security/groups"

    def create(self, group: Group) -> Group:
        """
        Creates a new group in Artifactory or replaces an existing group
        :param group: Group to create
        :return: Created group
        """
        group_name = group.name
        try:
            self.get(group_name)
            logger.error("Group %s already exists", group_name)
            raise GroupAlreadyExistsException(f"Group {group_name} already exists")
        except GroupNotFoundException:
            self._put(f"api/{self._uri}/{group_name}", json=group.dict())
            logger.debug("Group %s successfully created", group_name)
            return self.get(group.name)

    def get(self, name: str) -> Group:
        """
        Get the details of an Artifactory Group
        :param name: Name of the group to retrieve
        :return: Found artifactory group
        """
        try:
            response = self._get(
                f"api/{self._uri}/{name}", params={"includeUsers": True}
            )
            logger.debug("Group %s found", name)
            return Group(**response.json())
        except requests.exceptions.HTTPError as error:
            if error.response.status_code == 404 or error.response.status_code == 400:
                logger.error("Group %s does not exist", name)
                raise GroupNotFoundException(f"Group {name} does not exist")
            raise ArtifactoryException from error

    def list(self) -> List[Group]:
        """
        Lists all the groups
        :return: GroupList
        """
        response = self._get(f"api/{self._uri}")
        logger.debug("List all groups successful")
        return [Group(**group) for group in response.json()]

    def update(self, group: Group) -> Group:
        """
        Updates an exiting group in Artifactory with the provided group details.
        :param group: Group to be updated
        :return: Updated group
        """
        group_name = group.name
        self.get(group_name)
        self._post(f"api/{self._uri}/{group_name}", json=group.dict())
        logger.debug("Group %s successfully updated", group_name)
        return self.get(group_name)

    def delete(self, name: str) -> None:
        """
        Removes a group
        :param name: Name of the group to delete
        :return: None
        """
        self.get(name)
        self._delete(f"api/{self._uri}/{name}")
        logger.debug("Group %s successfully deleted", name)


class ArtifactoryRepository(ArtifactoryObject):
    """Models an artifactory repository."""

    _uri = "repositories"

    # Repositories operations
    def get_repo(self, repo_name: str) -> AnyRepositoryResponse:
        """
        Finds repository in artifactory. Raises an exception if the repo doesn't exist.
        :param repo_name: Name of the repository to retrieve
        :return: Either a local, virtual or remote repository
        """
        try:
            response = self._get(f"api/{self._uri}/{repo_name}")
            repo: AnyRepositoryResponse = parse_obj_as(
                Union[
                    LocalRepositoryResponse,
                    VirtualRepositoryResponse,
                    RemoteRepositoryResponse,
                ],
                response.json(),
            )
            return repo
        except requests.exceptions.HTTPError as error:
            if error.response.status_code == 404 or error.response.status_code == 400:
                logger.error("Repository %s does not exist", repo_name)
                raise RepositoryNotFoundException(
                    f" Repository {repo_name} does not exist"
                )
            raise ArtifactoryException from error

    def create_repo(self, repo: AnyRepository) -> AnyRepositoryResponse:
        """
        Creates a local, virtual or remote repository
        :param repo: Either a local, virtual or remote repository
        :return: LocalRepositoryResponse, VirtualRepositoryResponse or RemoteRepositoryResponse object
        """
        repo_name = repo.key
        try:
            self.get_repo(repo_name)
            logger.error("Repository %s already exists", repo_name)
            raise RepositoryAlreadyExistsException(
                f"Repository {repo_name} already exists"
            )
        except RepositoryNotFoundException:
            self._put(f"api/{self._uri}/{repo_name}", json=repo.dict())
            logger.debug("Repository %s successfully created", repo_name)
            return self.get_repo(repo_name)

    def update_repo(self, repo: AnyRepository) -> AnyRepositoryResponse:
        """
        Updates a local, virtual or remote repository
        :param repo: Either a local, virtual or remote repository
        :return: LocalRepositoryResponse, VirtualRepositoryResponse or RemoteRepositoryResponse object
        """
        repo_name = repo.key
        self.get_repo(repo_name)
        self._post(f"api/{self._uri}/{repo_name}", json=repo.dict())
        logger.debug("Repository %s successfully updated", repo_name)
        return self.get_repo(repo_name)


class ArtifactoryPermission(ArtifactoryObject):
    """Models an artifactory permission."""

    _uri = "security/permissions"

    def create(self, permission: Permission) -> Permission:
        """
        Creates a permission
        :param permission: Permission object
        :return: Permission
        """
        permission_name = permission.name
        try:
            self.get(permission_name)
            logger.debug("Permission %s already exists", permission_name)
            raise PermissionAlreadyExistsException(
                f"Permission {permission_name} already exists"
            )
        except PermissionNotFoundException:
            self._put(f"api/{self._uri}/{permission_name}", json=permission.dict())
            logger.debug("Permission %s successfully created", permission_name)
            return self.get(permission_name)

    def get(self, permission_name: str) -> Permission:
        """
        Read permission from artifactory. Fill object if exist
        :param permission_name: Name of the permission to retrieve
        :return: Permission
        """
        try:
            response = self._get(f"api/{self._uri}/{permission_name}")
            logger.debug("Permission %s found", permission_name)
            return Permission(**response.json())
        except requests.exceptions.HTTPError as error:
            if error.response.status_code == 404 or error.response.status_code == 400:
                logger.error("Permission %s does not exist", permission_name)
                raise PermissionNotFoundException(
                    f"Permission {permission_name} does not exist"
                )
            raise ArtifactoryException from error

    def list(self) -> List[SimplePermission]:
        """
        Lists all the permissions
        :return: A list of permissions
        """
        response = self._get(f"api/{self._uri}")
        logger.debug("List all permissions successful")
        return [SimplePermission(**permission) for permission in response.json()]

    def update(self, permission: Permission) -> Permission:
        """
        Updates an artifactory permission
        :param permission: Permission object
        :return: Permission
        """
        permission_name = permission.name
        self._put(f"api/{self._uri}/{permission_name}", json=permission.dict())
        logger.debug("Permission %s successfully updated", permission_name)
        return self.get(permission_name)

    def delete(self, permission_name: str) -> None:
        """
        Removes an artifactory permission
        :param permission_name: Name of the permission to delete
        :return: None
        """
        self.get(permission_name)
        self._delete(f"api/{self._uri}/{permission_name}")
        logger.debug("Permission %s successfully deleted", permission_name)


class ArtifactoryArtifact(ArtifactoryObject):
    """Models an artifactory artifact."""

    def info(self, artifact_path: str) -> ArtifactInfoResponse:
        """
        Retrieve information about a file or a folder

        See https://www.jfrog.com/confluence/display/JFROG/Artifactory+REST+API#ArtifactoryRESTAPI-FolderInfo
        and https://www.jfrog.com/confluence/display/JFROG/Artifactory+REST+API#ArtifactoryRESTAPI-FileInfo

        :param artifact_path: Path to file or folder in Artifactory
        """
        artifact_path = artifact_path.lstrip("/")
        try:
            response = self._get(f"api/storage/{artifact_path}")
            artifact_info: ArtifactInfoResponse = parse_obj_as(
                Union[ArtifactFolderInfoResponse, ArtifactFileInfoResponse],
                response.json(),
            )
            return artifact_info
        except requests.exceptions.HTTPError as error:
            if error.response.status_code == 404:
                logger.error("Artifact %s does not exist", artifact_path)
                raise ArtifactNotFoundException(
                    f"Artifact {artifact_path} does not exist"
                )
            raise ArtifactoryException from error

    def deploy(
        self, local_file_location: str, artifact_path: str
    ) -> ArtifactInfoResponse:
        """
        :param artifact_path: Path to file in Artifactory
        :param local_file_location: Location of the file to deploy
        """
        artifact_path = artifact_path.lstrip("/")
        local_filename = artifact_path.split("/")[-1]
        with open(local_file_location, "rb") as file:
            self._put(f"{artifact_path}", data=file)
            logger.debug("Artifact %s successfully deployed", local_filename)
            return self.info(artifact_path)

    def download(self, artifact_path: str, local_directory_path: str = None) -> str:
        """
        :param artifact_path: Path to file in Artifactory
        :param local_directory_path: Local path to where the artifact will be imported
        :return: File name
        """
        artifact_path = artifact_path.lstrip("/")
        local_filename = artifact_path.split("/")[-1]

        if local_directory_path:
            Path(local_directory_path).mkdir(parents=True, exist_ok=True)
            local_file_full_path = f"{local_directory_path}/{local_filename}"
        else:
            local_file_full_path = local_filename

        with self._get(f"{artifact_path}", stream=True) as response:
            with open(local_file_full_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:  # filter out keep-alive new chunks
                        file.write(chunk)
        logger.debug("Artifact %s successfully downloaded", local_filename)
        return local_file_full_path

    def properties(
        self, artifact_path: str, properties: Optional[List[str]] = None
    ) -> ArtifactPropertiesResponse:
        """
        :param artifact_path: Path to file in Artifactory
        :param properties: List of properties to retrieve
        :return: Artifact properties
        """
        if properties is None:
            properties = []
        artifact_path = artifact_path.lstrip("/")
        try:
            response = self._get(
                f"api/storage/{artifact_path}",
                params={"properties": ",".join(properties)},
            )
            logger.debug("Artifact Properties successfully retrieved")
            return ArtifactPropertiesResponse(**response.json())
        except requests.exceptions.HTTPError as error:
            if error.response.status_code == 404:
                raise PropertyNotFoundException(
                    f"Properties {properties} were not found on artifact {artifact_path}"
                )
            raise ArtifactoryException from error

    def stats(self, artifact_path: str) -> ArtifactStatsResponse:
        """
        :param artifact_path: Path to file in Artifactory
        :return: Artifact Stats
        """
        artifact_path = artifact_path.lstrip("/")
        response = self._get(f"api/storage/{artifact_path}?stats")
        logger.debug("Artifact stats successfully retrieved")
        return ArtifactStatsResponse(**response.json())

    def copy(
        self, artifact_current_path: str, artifact_new_path: str, dryrun: bool = False
    ) -> ArtifactInfoResponse:
        """
        :param artifact_current_path: Current path to file
        :param artifact_new_path: New path to file
        :param dryrun: Dry run
        :return: ArtifactInfoResponse: info of the copied artifact
        """
        artifact_current_path = artifact_current_path.lstrip("/")
        artifact_new_path = artifact_new_path.lstrip("/")
        if dryrun:
            dry = 1
        else:
            dry = 0

        self._post(f"api/copy/{artifact_current_path}?to={artifact_new_path}&dry={dry}")
        logger.debug("Artifact %s successfully copied", artifact_current_path)
        return self.info(artifact_new_path)

    def move(
        self, artifact_current_path: str, artifact_new_path: str, dryrun: bool = False
    ) -> ArtifactInfoResponse:
        """
        :param artifact_current_path: Current path to file
        :param artifact_new_path: New path to file
        :param dryrun: Dry run
        :return: ArtifactInfoResponse: info of the moved artifact
        """
        artifact_current_path = artifact_current_path.lstrip("/")
        artifact_new_path = artifact_new_path.lstrip("/")

        if dryrun:
            dry = 1
        else:
            dry = 0

        self._post(f"api/move/{artifact_current_path}?to={artifact_new_path}&dry={dry}")
        logger.debug("Artifact %s successfully moved", artifact_current_path)
        return self.info(artifact_new_path)

    def delete(self, artifact_path: str) -> None:
        """
        :param artifact_path: Path to file in Artifactory
        :return: bool
        """
        artifact_path = artifact_path.lstrip("/")
        self._delete(f"{artifact_path}")
        logger.debug("Artifact %s successfully deleted", artifact_path)


def create_aql_query(aql_object: Aql) -> str:
    """
    :param aql_object: Aql object
    :return: Well formatted aql query
    """
    aql_query_text = f"{aql_object.domain}.find"

    if aql_object.find:
        aql_query_text += f"({json.dumps(aql_object.find)})"
    else:
        aql_query_text += "()"

    if aql_object.include:
        format_include = (
            json.dumps(aql_object.include).replace("[", "").replace("]", "")
        )
        aql_query_text += f".include({format_include})"

    if aql_object.sort:
        sort_key = list(aql_object.sort.keys())[0]
        sort_value = json.dumps(aql_object.sort[sort_key])
        aql_query_text += f'.sort({{"{sort_key.value}": {sort_value}}})'

    if aql_object.offset:
        aql_query_text += f".offset({aql_object.offset})"

    if aql_object.limit:
        aql_query_text += f".limit({aql_object.limit})"

    return aql_query_text


class ArtifactoryAql(ArtifactoryObject):
    """Models an artifactory Aql object."""

    _uri = "search/aql"

    def query(self, aql_object: Aql) -> List[Dict[str, Union[str, List]]]:
        """
        :param aql_object: Aql object
        :return: The result of the aql query
        """
        aql_query = create_aql_query(aql_object)
        try:
            response = self._post(f"api/{self._uri}", data=aql_query)
            response_content: List[Dict[str, Union[str, List]]] = response.json()[
                "results"
            ]
            logging.debug("Successful query")
            return response_content
        except requests.exceptions.HTTPError:
            raise AqlException(
                "Bad Aql Query: please check your parameters."
                "Doc: https://www.jfrog.com/confluence/display/RTF/Artifactory+Query+Language"
            )
